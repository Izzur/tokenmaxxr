"""Ollama Cloud provider.

URL: https://ollama.com/settings
Anchors on the usage meters' aria-labels. Two plan shapes:
legacy plans show "Session usage N% used" (5h) + "Weekly usage N% used" (7d),
reset read from the sibling element's data-time (ISO 8601);
credits plans (Pro/Max) show one dollar budget, "Monthly credits used: $X of $Y"
(30d), reset parsed from the "Refills to $Y in 1 week." text (no timestamp).
"""

from __future__ import annotations

from http.cookiejar import CookieJar
import re

from bs4 import BeautifulSoup

from tokenmaxxr.providers.base import Provider, RawHtml, register
from tokenmaxxr.reset import parse_iso_utc, parse_relative_to_utc
from tokenmaxxr.schema import UsageWindow

DASHBOARD_URL = "https://ollama.com/settings"

# An aria-label like "Session usage 47% used" → label "Session", pct 47.
# Ollama's settings page renders decimals ("31.7% used") and an optional
# " used" suffix, so we accept both.
_LABEL_RE = re.compile(
    r"^(Session|Weekly|Daily|Monthly)\s+usage\s+(\d+(?:\.\d+)?)\s*%\s*(?:used)?\s*$",
    re.IGNORECASE,
)
# Credits plans: "Monthly credits used: $10.18 of $60". Loose between the
# kind and the amounts, since Ollama rewords it (was "Monthly usage $X of $Y used").
_DOLLAR_RE = re.compile(
    r"^(Session|Weekly|Daily|Monthly)\b[^$]*\$([\d,.]+)\s+of\s+\$([\d,.]+)",
    re.IGNORECASE,
)
_REFILL_RE = re.compile(r"\brefills?\b", re.IGNORECASE)


class OllamaCloudProvider:
    slug = "ollama-cloud"
    name = "Ollama Cloud"
    cookie_domain = "ollama.com"

    def fetch_raw(self, cookies: CookieJar) -> RawHtml:
        from tokenmaxxr.providers.base import make_session

        sess = make_session(cookies)
        r = sess.get(DASHBOARD_URL, timeout=20)
        r.raise_for_status()
        return RawHtml(url=r.url, text=r.text)

    def to_rows(self, raw: RawHtml) -> list[UsageWindow]:
        soup = BeautifulSoup(raw.text, "html.parser")
        windows: list[UsageWindow] = []
        for el in soup.find_all(attrs={"aria-label": True}):
            label_attr = el.get("aria-label", "")
            parsed = _parse(label_attr.strip())
            if parsed is None:
                continue
            pct, used, cap = parsed
            kind = label_attr.split(None, 1)[0]
            # $ meter has no timestamp nearby; walking up for data-time would
            # hit the "Recent requests" table and report a past request time.
            reset_at = _refill_reset_iso(soup) if cap is not None else _sibling_reset_iso(el)
            windows.append(
                UsageWindow(
                    label=_label_for(kind),
                    pct_used=pct,
                    reset_at=reset_at,
                    used=used,
                    limit=cap,
                    unit="$" if cap is not None else None,
                )
            )
        if not windows:
            raise RuntimeError("no usage aria-labels found on ollama settings")
        return windows


def _parse(label: str) -> tuple[int, float | None, float | None] | None:
    """aria-label → (pct, used $, limit $); dollars only on credits plans."""
    used = cap = None
    try:
        if m := _LABEL_RE.match(label):
            pct = float(m.group(2))
        elif m := _DOLLAR_RE.match(label):
            used, cap = (float(g.replace(",", "")) for g in m.group(2, 3))
            pct = used / cap * 100
        else:
            return None
    except (ValueError, ZeroDivisionError):
        return None
    return max(0, min(100, int(round(pct)))), used, cap


def _sibling_reset_iso(el) -> str | None:
    parent = el.parent
    for _ in range(6):
        if parent is None:
            break
        sibling = parent.find(attrs={"data-time": True})
        if sibling:
            return parse_iso_utc(sibling["data-time"])
        parent = parent.parent
    return None


def _refill_reset_iso(soup) -> str | None:
    # ponytail: the page only says "in 1 week", so this can be up to one unit
    # early; /settings/billing has the exact renewal date (monthly billing only).
    text = soup.find(string=_REFILL_RE)
    return parse_relative_to_utc(str(text)) if text else None


def _label_for(kind: str) -> str:
    k = kind.lower()
    if k == "session":
        return "5h"
    if k == "weekly":
        return "7d"
    if k == "daily":
        return "24h"
    if k == "monthly":
        return "30d"
    return kind


register(OllamaCloudProvider.slug, OllamaCloudProvider)
