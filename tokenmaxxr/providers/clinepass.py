"""ClinePass provider.

Cline's dashboard (app.cline.bot) is a Next.js SPA shell — server-rendered
HTML has no usage cards; data is fetched client-side from api.cline.bot.
The auth cookie (cline_session_id) is host-locked to api.cline.bot, so
resolving cookies for app.cline.bot alone misses the auth and every API
call returns 401.

Strategy: resolve cookies for BOTH app.cline.bot and api.cline.bot and
merge. Then hit the JSON API directly — it's the only source of truth.
"""

from __future__ import annotations

from http.cookiejar import CookieJar

from tokenmaxxr.cookies import resolve as resolve_cookies
from tokenmaxxr.providers.base import RawHtml, make_session, register
from tokenmaxxr.reset import parse_iso_utc
from tokenmaxxr.schema import UsageWindow

DASHBOARD_URL = (
    "https://app.cline.bot/dashboard/subscription?personal=true"
)
# The actual source of truth for quota.
_USAGE_LIMITS_URL = "https://api.cline.bot/api/v1/users/me/plan/usage-limits"
_AUTH_PROBE_URL = "https://api.cline.bot/api/v1/users/me"

# Map the API's "type" field to canonical labels used everywhere else.
_TYPE_TO_LABEL = {
    "five_hour": "5h",
    "weekly": "7d",
    "monthly": "30d",
}


def _merge_cookies(*jars: CookieJar | None) -> CookieJar:
    """Return a new jar containing every cookie from each input."""
    out = CookieJar()
    for jar in jars:
        if not jar:
            continue
        for c in jar:
            # Last write wins on duplicate (name, domain, path) — the
            # API-domain cookie overwrites the app-domain one if they
            # share a name, which is what we want for cline_session_id.
            out.set_cookie(c)
    return out


class ClinePassProvider:
    slug = "clinepass"
    name = "ClinePass"
    cookie_domain = "app.cline.bot"

    def fetch_raw(self, cookies: CookieJar) -> RawHtml:
        # cookies argument is the app.cline.bot jar. Augment with the
        # api.cline.bot jar so cline_session_id is included.
        api_jar, _ = resolve_cookies("api.cline.bot")
        merged = _merge_cookies(cookies, api_jar)
        sess = make_session(merged)
        # Auth probe first: if cline_session_id is invalid, the dashboard
        # page comes back empty AND the API returns 401. We only need the
        # API response either way, so use it for the auth signal too.
        try:
            probe = sess.get(_AUTH_PROBE_URL, timeout=10)
        except Exception:
            probe = None
        auth_status = probe.status_code if probe is not None else None
        try:
            limits = sess.get(_USAGE_LIMITS_URL, timeout=10)
        except Exception:
            limits = None
        usage_status = limits.status_code if limits is not None else None
        usage_text = limits.text if limits is not None else None
        return RawHtml(
            url=_USAGE_LIMITS_URL,
            text=usage_text or "",
            auth_status=auth_status,
            usage_status=usage_status,
        )

    def to_rows(self, raw: RawHtml) -> list[UsageWindow]:
        if raw.auth_status == 401 or raw.usage_status == 401:
            raise RuntimeError(
                "session expired — open https://app.cline.bot/dashboard/subscription "
                "in your browser to refresh, then retry"
            )
        if raw.usage_status is None or raw.usage_status >= 400:
            raise RuntimeError(
                f"clinepass API returned {raw.usage_status}: {raw.text[:200]}"
            )
        import json

        try:
            data = json.loads(raw.text)
        except (TypeError, ValueError) as e:
            raise RuntimeError(f"clinepass API returned non-JSON: {e}") from e
        limits = (data.get("data") or {}).get("limits") or []
        windows: list[UsageWindow] = []
        for entry in limits:
            t = entry.get("type")
            label = _TYPE_TO_LABEL.get(t or "")
            if not label:
                continue
            try:
                pct = int(round(float(entry.get("percentUsed", 0))))
            except (TypeError, ValueError):
                continue
            pct = max(0, min(100, pct))
            reset = entry.get("resetsAt")
            reset_at = parse_iso_utc(reset) if reset else None
            windows.append(UsageWindow(label=label, pct_used=pct, reset_at=reset_at))
        if not windows:
            raise RuntimeError("clinepass API returned no usage limits")
        return windows


register(ClinePassProvider.slug, ClinePassProvider)
