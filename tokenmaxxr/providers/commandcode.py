"""Command Code provider.

commandcode.ai/<user>/settings/usage is a React Router SPA shell; the data
comes from api.commandcode.ai with the browser session cookie
(`__Secure-commandcode_prod_.session_token`, domain `.commandcode.ai`).

Two calls:
- GET /internal/billing/credits — `windowLimits.fiveHour` / `.weekly`
  (`used`, `cap` in dollars, `resetAt` ms epoch) and monthly credits
  (`monthlyCreditsGranted`, `monthlyCredits` = remaining).
- GET /internal/billing/subscriptions — `data.currentPeriodEnd` (ISO) used as
  the 30d reset.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.cookiejar import CookieJar

from tokenmaxxr.providers.base import NoAuth, RawHtml, make_session, register
from tokenmaxxr.reset import parse_iso_utc
from tokenmaxxr.schema import UsageWindow

API = "https://api.commandcode.ai"
CREDITS_URL = f"{API}/internal/billing/credits"
SUBSCRIPTIONS_URL = f"{API}/internal/billing/subscriptions"
LOGIN_URL = "https://commandcode.ai/settings/usage"

_WINDOWS = (("fiveHour", "5h"), ("weekly", "7d"))


class CommandCodeProvider:
    slug = "commandcode"
    name = "Command Code"
    cookie_domain = "commandcode.ai"

    def fetch_raw(self, cookies: CookieJar) -> RawHtml:
        sess = make_session(cookies)
        sess.headers.update({"Accept": "application/json", "Origin": "https://commandcode.ai"})
        credits = sess.get(CREDITS_URL, timeout=15)
        subs = sess.get(SUBSCRIPTIONS_URL, timeout=15)
        # Bundle both bodies; subscriptions is best-effort (only supplies the 30d reset).
        body = {
            "credits": _json_or_none(credits.text) if credits.ok else None,
            "subscription": (_json_or_none(subs.text) or {}).get("data") if subs.ok else None,
        }
        return RawHtml(
            url=CREDITS_URL,
            text=json.dumps(body),
            auth_status=credits.status_code,
            usage_status=credits.status_code,
        )

    def to_rows(self, raw: RawHtml) -> list[UsageWindow]:
        if raw.usage_status in (401, 403):
            raise NoAuth(f"Command Code session expired — open {LOGIN_URL} in your browser, then retry")
        if raw.usage_status is None or raw.usage_status >= 400:
            raise RuntimeError(f"commandcode API returned {raw.usage_status}")
        body = _json_or_none(raw.text) or {}
        data = body.get("credits") or {}
        windows: list[UsageWindow] = []
        limits = data.get("windowLimits") or {}
        if limits.get("limited"):
            for key, label in _WINDOWS:
                w = limits.get(key) or {}
                cap, used = _num(w.get("cap")), _num(w.get("used"))
                if cap > 0:
                    windows.append(
                        UsageWindow(
                            label=label,
                            pct_used=_pct(used, cap),
                            reset_at=_ms_iso(w.get("resetAt")),
                            used=round(used, 2),
                            limit=cap,
                            unit="$",
                        )
                    )
        credits = data.get("credits") or {}
        granted = _num(credits.get("monthlyCreditsGranted"))
        if granted > 0:
            remaining = _num(credits.get("monthlyCredits"))
            period_end = (body.get("subscription") or {}).get("currentPeriodEnd")
            windows.append(
                UsageWindow(
                    label="30d",
                    pct_used=_pct(granted - remaining, granted),
                    reset_at=parse_iso_utc(period_end) if period_end else None,
                    used=round(granted - remaining, 2),
                    limit=granted,
                    unit="credits",
                )
            )
        if not windows:
            raise RuntimeError("commandcode API returned no limits (pay-as-you-go plan?)")
        return windows


def _json_or_none(text: str):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _num(v) -> float:
    return float(v) if isinstance(v, (int, float)) else 0.0


def _pct(used: float, limit: float) -> int:
    return max(0, min(100, int(round(used / limit * 100)))) if limit > 0 else 0


def _ms_iso(v) -> str | None:
    if not isinstance(v, (int, float)):
        return None
    return datetime.fromtimestamp(v / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


register(CommandCodeProvider.slug, CommandCodeProvider)
