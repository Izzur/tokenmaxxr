"""Nous Portal provider.

Two auth paths; the first wins once `tokenmaxxr login nous-portal` has run.

1. Own OAuth login: the device flow Hermes Agent uses. The portal only accepts
   known client IDs (anything else gets 400 invalid_client), so we borrow
   Hermes' `hermes-cli`. Our token pair lives in
   $XDG_STATE_HOME/tokenmaxxr/nous-portal-auth.json (0600; state, not config,
   so dotfile sync never copies it to a second machine). GET /api/oauth/account
   returns `"subscription": {"monthly_credits", "credits_remaining",
   "current_period_end", "rollover_credits", ...}` in dollars. Access tokens
   last 15-60 min. Refresh tokens are single-use and redeeming one twice
   revokes the whole chain, so refreshes run under a file lock and the rotated
   pair is on disk before it is used.

2. Browser cookies: portal.nousresearch.com/billing redirects to
   /orgs/<last_selected_org>/billing, a Next.js page whose RSC payload
   (`self.__next_f.push` chunks) carries `"subscription": {"active": {"tier",
   "monthlyCredits", "currentPeriodEnd", ...}, "credits": {"balance",
   "rolloverCredits"}}`. The page accepts the browser's short-lived
   `privy-token` (1h) or `nas-session` (15m) cookie. Once both are stale it
   redirects to /api/auth/refresh, which rotates `nas-refresh`; we never send
   that cookie, so polling cannot sign the browser out. A stale session
   bounces to /refresh (client-side Privy refresh) or /login instead.

Both report one 30d window: used = monthly credits - balance (the page's
"Spent This Period"). Inference API keys can't read any of this: they get 401
from /api/oauth/account and completions carry no credit headers.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlparse

from tokenmaxxr.cache import state_dir
from tokenmaxxr.providers.base import NoAuth, RawHtml, make_session, register
from tokenmaxxr.reset import parse_iso_utc
from tokenmaxxr.schema import UsageWindow

PORTAL = "https://portal.nousresearch.com"
BILLING_URL = f"{PORTAL}/billing"
ACCOUNT_URL = f"{PORTAL}/api/oauth/account"
TOKEN_URL = f"{PORTAL}/api/oauth/token"
CLIENT_ID = "hermes-cli"
# Vercel's bot checkpoint answers 429 to non-browser User-Agents.
_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
_SUB_KEY = '"subscription":'
# OAuth errors that mean the refresh token is dead (Hermes Agent's list).
_DEAD_GRANT = ("invalid_grant", "invalid_token", "refresh_token_reused")


def auth_path() -> Path:
    return state_dir() / "nous-portal-auth.json"


class NousPortalProvider:
    slug = "nous-portal"
    name = "Nous Portal"

    @property
    def cookie_domain(self) -> str | None:
        # None makes fetch_all skip cookie lookup and pass cookies=None: we have our own login.
        return None if auth_path().exists() else "portal.nousresearch.com"

    def auth_hint(self) -> str:
        return f"{auth_path()} (from `tokenmaxxr login nous-portal`)"

    def fetch_raw(self, cookies: CookieJar | None) -> RawHtml:
        if cookies is None:
            sess = _api_session()
            sess.headers["Authorization"] = f"Bearer {_access_token()}"
            r = sess.get(ACCOUNT_URL, timeout=20)
            return RawHtml(url=ACCOUNT_URL, text=r.text, usage_status=r.status_code)
        jar = CookieJar()
        for c in cookies:
            if c.name != "nas-refresh":
                jar.set_cookie(c)
        r = make_session(jar, user_agent=_UA).get(BILLING_URL, timeout=20)
        return RawHtml(url=r.url, text=r.text, usage_status=r.status_code)

    def to_rows(self, raw: RawHtml) -> list[UsageWindow]:
        if raw.url == ACCOUNT_URL:
            if raw.usage_status == 401:
                raise NoAuth("Nous Portal rejected the saved login — run `tokenmaxxr login nous-portal`")
            if raw.usage_status != 200:
                raise RuntimeError(f"nous portal account API returned {raw.usage_status}")
            sub = json.loads(raw.text).get("subscription") or {}
            return _window(sub.get("monthly_credits"), sub.get("credits_remaining"), sub.get("current_period_end"))
        path = urlparse(raw.url).path
        if "/billing" not in path:
            raise NoAuth(
                f"Nous Portal session expired (sent to {path}) — run `tokenmaxxr login nous-portal` once, "
                f"or open {BILLING_URL} in your browser"
            )
        if raw.usage_status != 200:
            raise RuntimeError(f"nous portal billing page returned {raw.usage_status}")
        # Rows can be split across chunks, so decode and join them all first.
        rsc = "".join(json.loads(f'"{s}"') for s in _PUSH_RE.findall(raw.text))
        i = rsc.find(_SUB_KEY + '{"active"')
        if i < 0:
            raise RuntimeError("no subscription data on the nous portal billing page")
        sub, _ = json.JSONDecoder().raw_decode(rsc, i + len(_SUB_KEY))
        active = sub.get("active") or {}
        return _window(active.get("monthlyCredits"), (sub.get("credits") or {}).get("balance"), active.get("currentPeriodEnd"))


def _window(monthly, balance, period_end) -> list[UsageWindow]:
    if not isinstance(monthly, (int, float)) or monthly <= 0:
        raise RuntimeError("no Nous Portal subscription credits (Free plan?)")
    if not isinstance(balance, (int, float)):
        raise RuntimeError("no credit balance in the Nous Portal response")
    # Rollover sits on top of the monthly grant; like Hermes, count spend against the grant only.
    used = max(0.0, monthly - balance)
    return [
        UsageWindow(
            label="30d",
            pct_used=max(0, min(100, int(round(used / monthly * 100)))),
            reset_at=parse_iso_utc(period_end or ""),
            used=round(used, 2),
            limit=float(monthly),
            unit="$",
        )
    ]


def login() -> None:
    """OAuth device flow (RFC 8628): print a link, wait for approval, save our token pair."""
    sess = _api_session()
    r = sess.post(f"{PORTAL}/api/oauth/device/code", data={"client_id": CLIENT_ID, "scope": "inference:invoke"}, timeout=20)
    r.raise_for_status()
    dev = r.json()
    print(f"Open {dev['verification_uri_complete']}\nand approve code {dev['user_code']} (the portal calls this login Hermes).", flush=True)
    interval, deadline = int(dev["interval"]), time.monotonic() + int(dev["expires_in"])
    while time.monotonic() < deadline:
        time.sleep(interval)
        r = sess.post(
            TOKEN_URL,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "client_id": CLIENT_ID, "device_code": dev["device_code"]},
            timeout=20,
        )
        if r.status_code == 200:
            with _locked():
                _save(r.json(), None)
            return
        err = _error_code(r)
        if err == "slow_down":
            interval += 5
        # No OAuth error code means the edge (Vercel 403/429, 5xx) got in the way: keep polling.
        elif err not in (None, "authorization_pending"):
            raise RuntimeError(f"Nous login failed: {err}")
    raise RuntimeError("Nous login timed out — run `tokenmaxxr login nous-portal` again")


def _access_token() -> str:
    """The saved access token, refreshed first when it has under 2 minutes left."""
    with _locked():
        try:
            saved = json.loads(auth_path().read_text())
        except (OSError, ValueError) as e:
            raise NoAuth(f"cannot read {auth_path()}: {e}") from e
        if saved["expires_at"] - time.time() > 120:
            return saved["access_token"]
        r = _api_session().post(
            TOKEN_URL,
            headers={"x-nous-refresh-token": saved["refresh_token"]},
            data={"grant_type": "refresh_token", "client_id": CLIENT_ID},
            timeout=20,
        )
        if r.status_code == 200:
            return _save(r.json(), saved["refresh_token"])
        err = _error_code(r)
        if err in _DEAD_GRANT or r.status_code == 401:
            auth_path().unlink()  # useless now; dropping it brings back the cookie path
            raise NoAuth(f"Nous Portal login expired ({err or 'HTTP 401'}) — run `tokenmaxxr login nous-portal`")
        raise RuntimeError(f"nous portal token refresh returned HTTP {r.status_code}")


def _save(tok: dict, old_refresh: str | None) -> str:
    """Write the pair before anything uses it (refresh tokens are single-use); returns the access token."""
    saved = {
        "access_token": tok["access_token"],
        # Like Hermes: a refresh reply without refresh_token keeps the old one.
        "refresh_token": tok.get("refresh_token") or old_refresh,
        "expires_at": time.time() + float(tok.get("expires_in") or 0),
    }
    tmp = auth_path().with_suffix(".tmp")
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(saved, f)
    os.replace(tmp, auth_path())
    return saved["access_token"]


@contextmanager
def _locked():
    """Serialize token refreshes across processes (DMS poll vs. a manual run)."""
    import fcntl  # POSIX-only; imported here so the other providers still load elsewhere

    auth_path().parent.mkdir(parents=True, exist_ok=True)
    with open(auth_path().with_suffix(".lock"), "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def _api_session():
    sess = make_session(CookieJar(), user_agent=_UA)
    sess.headers["Accept"] = "application/json"
    return sess


def _error_code(r) -> str | None:
    try:
        return r.json().get("error")
    except ValueError:
        return None


register(NousPortalProvider.slug, NousPortalProvider)
