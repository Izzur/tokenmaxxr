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

    # 4. Chromium-family via browser_cookie3 (best-effort).
    try:
        import browser_cookie3  # type: ignore

        jar_funcs: list[tuple[str, CookieJar]] = [
            ("chrome", lambda: browser_cookie3.chrome(domain_name=domain)),
            ("chromium", lambda: browser_cookie3.chromium(domain_name=domain)),
            ("edge", lambda: browser_cookie3.edge(domain_name=domain)),
            ("brave", lambda: browser_cookie3.brave(domain_name=domain)),
            ("opera", lambda: browser_cookie3.opera(domain_name=domain)),
            ("vivaldi", lambda: browser_cookie3.vivaldi(domain_name=domain)),
        ]
        for kind, mk in jar_funcs:
            try:
                jar = mk()
            except Exception:  # noqa: BLE001 — locked keyring, missing keyring, etc.
                continue
            if any(_cookie_matches_domain(c, domain) for c in jar):
                # Reduce jar to the requested domain so requests only sends
                # cookies for the target host.
                pruned = _prune_jar(jar, domain)
                return pruned, CookieSource(
                    "chromium", kind, (domain,)
                )
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        log.debug("chromium discovery failed: %s", e)

    return None, None


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
            _cookies, hosts = _read_firefox_db(path, domain)
        except sqlite3.OperationalError:
            continue
        if hosts:
            found.append(CookieSource("firefox", str(path), tuple(hosts)))
    # Chromium: best-effort probe so the doctor output only mentions
    # Chromium when a Chromium-family store actually loaded. Locked
    # keyring / missing browser_cookie3 → silent skip.
    try:
        import browser_cookie3  # type: ignore

        for kind, loader in (
            ("chrome", browser_cookie3.chrome),
            ("chromium", browser_cookie3.chromium),
            ("edge", browser_cookie3.edge),
            ("brave", browser_cookie3.brave),
            ("opera", browser_cookie3.opera),
            ("vivaldi", browser_cookie3.vivaldi),
        ):
            try:
                jar = loader(domain_name=domain)
            except Exception:  # noqa: BLE001 — locked keyring, missing browser, etc.
                continue
            if any(_cookie_matches_domain(c, domain) for c in jar):
                found.append(CookieSource("chromium", kind, (domain,)))
    except ImportError:
        pass
    return found
