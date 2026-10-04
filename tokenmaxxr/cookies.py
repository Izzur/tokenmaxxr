"""Browser-agnostic cookie resolution.

Order: override (CLI / env) → Firefox-family stores (globbed) →
Chromium-family (browser_cookie3) → no match.
Always copies the cookie DB to a temp file before reading (WAL-safe).
Never writes to any browser store.
"""

from __future__ import annotations

import glob
import logging
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

FIREFOX_GLOBS: tuple[str, ...] = (
    # Real Firefox
    "~/.mozilla/firefox/*/cookies.sqlite",
    # Zen (native install)
    "~/.zen/*/cookies.sqlite",
    # Zen Flatpak
    "~/.var/app/app.zen_browser.zen/.zen/*/cookies.sqlite",
    # Firefox Flatpak
    "~/.var/app/org.mozilla.firefox/.mozilla/firefox/*/cookies.sqlite",
    # Firefox forks: Floorp, LibreWolf, Waterfox
    "~/.var/app/one.floorp.floorp/.floorp/*/cookies.sqlite",
    "~/.var/app/io.github.nickvision.nickvisionapp/.librewolf/*/cookies.sqlite",
    "~/.var/app/io.github.nickvision.nickvisionapp/.waterfox/*/cookies.sqlite",
)

# Chromium-family cookie DBs, mirroring browser_cookie3's Linux paths. Only
# browsers with a DB on disk get probed: browser_cookie3 asks the OS keyring
# for the decryption key *before* checking the cookie file exists, and when
# KDE Wallet is locked it then calls hasFolder/close with handle -1, which
# ksecretd counts as failures and surfaces as a "misbehaving app" popup.
CHROMIUM_GLOBS: dict[str, tuple[str, ...]] = {
    "chrome": (
        "~/.config/google-chrome*/*/Cookies",
        "~/.var/app/com.google.Chrome/config/google-chrome*/*/Cookies",
    ),
    "chromium": (
        "~/.config/chromium/*/Cookies",
        "~/.var/app/org.chromium.Chromium/config/chromium/*/Cookies",
    ),
    "edge": (
        "~/.config/microsoft-edge*/*/Cookies",
        "~/.var/app/com.microsoft.Edge/config/microsoft-edge*/*/Cookies",
    ),
    "brave": (
        "~/.config/BraveSoftware/Brave-Browser*/*/Cookies",
        "~/.var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser*/*/Cookies",
    ),
    "opera": (
        "~/.config/opera*/Cookies",
        "~/.var/app/com.opera.Opera/config/opera*/Cookies",
    ),
    "vivaldi": (
        "~/.config/vivaldi*/*/Cookies",
        "~/.var/app/com.vivaldi.Vivaldi/config/vivaldi/*/Cookies",
    ),
}


@dataclass(frozen=True)
class CookieSource:
    """Diagnostic info for `doctor` — which source actually produced cookies."""
    kind: str            # "override", "firefox", "chromium"
    detail: str          # path or label, never cookie values
    domains: tuple[str, ...]  # domains covered by this source


def _expand(p: str) -> str:
    return os.path.expanduser(os.path.expandvars(p))


def _glob_paths() -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for pat in FIREFOX_GLOBS:
        for m in glob.glob(_expand(pat)):
            p = Path(m).resolve()
            if p.exists() and p not in seen:
                seen.add(p)
                out.append(p)
    return out


def _copy_db_to_temp(src: Path) -> Path:
    fd, name = tempfile.mkstemp(prefix="tokenmaxxr-cookies-", suffix=".sqlite")
    os.close(fd)
    shutil.copyfile(src, name)
    return Path(name)


def _read_firefox_db(
    src: Path, domain: str
) -> tuple[list[Cookie], list[str]]:
    """Return (cookies, host_keys_seen) from a Firefox-style cookies.sqlite."""
    cookies: list[Cookie] = []
    hosts: set[str] = set()
    tmp = _copy_db_to_temp(src)
    try:
        # Detect schema: new Firefox uses `host`/`isSecure`/`isHttpOnly`,
        # old uses `host_key`/`is_secure`/`is_httponly`.
        with sqlite3.connect(tmp) as conn:
            cols = {
                r[1]
                for r in conn.execute("PRAGMA table_info(moz_cookies)")
            }
            host_col = "host" if "host" in cols else "host_key"
            secure_col = "isSecure" if "isSecure" in cols else "is_secure"
            httponly_col = "isHttpOnly" if "isHttpOnly" in cols else "is_httponly"
            cur = conn.execute(
                f"SELECT name, value, {host_col}, path, "
                "datetime(expiry, 'unixepoch'), "
                f"{secure_col}, {httponly_col} "
                "FROM moz_cookies"
            )
            for name, value, host_key, path, expires, secure, httponly in cur:
                hosts.add(host_key)
                if not _host_matches(host_key, domain):
                    continue
                # SQLite sometimes returns a string for datetime; keep as-is.
                expires_ts: float | None = None
                if expires:
                    try:
                        from datetime import datetime
                        expires_ts = datetime.strptime(
                            expires, "%Y-%m-%d %H:%M:%S"
                        ).timestamp()
                    except ValueError:
                        expires_ts = None
                cookies.append(
                    Cookie(
                        version=0, name=name, value=value,
                        domain=host_key.lstrip("."), domain_specified=False,
                        domain_initial_dot=host_key.startswith("."),
                        path=path or "/",
                        path_specified=True,
                        secure=bool(secure),
                        expires=expires_ts,
                        discard=False,
                        comment=None, comment_url=None,
                        rest={}, rfc2109=False,
                        port=None, port_specified=False,
                    )
                )
                if host_key.startswith("https://"):
                    cookies[-1].secure = True
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return cookies, sorted(hosts)


def _host_matches(host_key: str, domain: str) -> bool:
    """Match Mozilla host_key (`.example.com` or `example.com`) to a domain."""
    hk = host_key.lstrip(".").lower()
    d = domain.lower().lstrip(".")
    if not hk or not d:
        return False
    if hk == d:
        return True
    if hk.endswith("." + d):
        return True
    if d.endswith("." + hk):
        return True
    return False


def resolve(
    domain: str,
    *,
    override: str | os.PathLike | None = None,
    env_prefix: str = "TOKENMAXXR_COOKIE_",
) -> tuple[CookieJar | None, CookieSource | None]:
    """Return (jar, source) for `domain`, or (None, None) when nothing matches.

    `override` is an explicit cookies.sqlite path; env var `${env_prefix}<DOMAIN>`
    (uppercased, dots → underscores) is honored as well.
    """
    # 1. Override (CLI flag).
    if override:
        path = Path(_expand(str(override)))
        if not path.exists():
            raise FileNotFoundError(f"--cookie-file not found: {path}")
        cookies, _hosts = _read_firefox_db(path, domain)
        if cookies:
            return _to_jar(cookies), CookieSource(
                "override", str(path), (domain,)
            )

    # 2. Env override.
    env_key = env_prefix + domain.upper().replace(".", "_")
    env_val = os.environ.get(env_key)
    if env_val:
        path = Path(_expand(env_val))
        if path.exists():
            cookies, _hosts = _read_firefox_db(path, domain)
            if cookies:
                return _to_jar(cookies), CookieSource(
                    "override", f"env {env_key}={path}", (domain,)
                )

    # 3. Firefox-family stores.
    for path in _glob_paths():
        try:
            cookies, hosts = _read_firefox_db(path, domain)
        except sqlite3.OperationalError as e:
            log.debug("skip %s: %s", path, e)
            continue
        if cookies:
            return _to_jar(cookies), CookieSource(
                "firefox", str(path), tuple(hosts)
            )

    # 4. Chromium-family via browser_cookie3 (installed browsers only).
    for kind, jar in _chromium_jars(domain):
        if any(_cookie_matches_domain(c, domain) for c in jar):
            # Reduce jar to the requested domain so requests only sends
            # cookies for the target host.
            return _prune_jar(jar, domain), CookieSource(
                "chromium", kind, (domain,)
            )

    return None, None


def _chromium_jars(domain: str) -> Iterable[tuple[str, CookieJar]]:
    """Yield (kind, jar) for each Chromium-family browser that has a cookie DB."""
    try:
        import browser_cookie3  # type: ignore
    except ImportError:
        return
    for kind, pats in CHROMIUM_GLOBS.items():
        if not any(glob.glob(_expand(p)) for p in pats):
            continue
        try:
            yield kind, getattr(browser_cookie3, kind)(domain_name=domain)
        except Exception as e:  # noqa: BLE001 — locked keyring, unreadable DB, etc.
            log.debug("skip %s: %s", kind, e)


def _cookie_matches_domain(c: Cookie, domain: str) -> bool:
    return _host_matches(c.domain, domain)


def _prune_jar(jar: CookieJar, domain: str) -> CookieJar:
    out = CookieJar()
    for c in jar:
        if _cookie_matches_domain(c, domain):
            out.set_cookie(c)
    return out


def _to_jar(cookies: Iterable[Cookie]) -> CookieJar:
    jar = CookieJar()
    for c in cookies:
        jar.set_cookie(c)
    return jar


def discover_sources(domain: str) -> list[CookieSource]:
    """Doctor helper: list which stores contain cookies for `domain`."""
    found: list[CookieSource] = []
    for path in _glob_paths():
        try:
            cookies, hosts = _read_firefox_db(path, domain)
        except sqlite3.OperationalError:
            continue
        if cookies:
            found.append(CookieSource("firefox", str(path), tuple(hosts)))
    # Chromium: only mention a Chromium-family store when one actually loaded.
    for kind, jar in _chromium_jars(domain):
        if any(_cookie_matches_domain(c, domain) for c in jar):
            found.append(CookieSource("chromium", kind, (domain,)))
    return found
