"""Ollama Cloud provider.

URL: https://ollama.com/dashboard
Two plan shapes:
legacy plans show aria-labels "Session usage N% used" (5h) + "Weekly usage N% used"
(7d), reset read from the sibling element's data-time (ISO 8601);
credits plans (Pro/Max) show a "Usage credits" card whose #usage-credits-breakdown
tooltip says "Monthly credits $LEFT" and "Refills to $CAP on November 18, 2026." (30d).
"""

from __future__ import annotations

from datetime import datetime, timezone
from http.cookiejar import CookieJar
import re

from bs4 import BeautifulSoup

from tokenmaxxr.providers.base import Provider, RawHtml, register
from tokenmaxxr.reset import parse_iso_utc
from tokenmaxxr.schema import UsageWindow

DASHBOARD_URL = "https://ollama.com/dashboard"

# An aria-label like "Session usage 47% used" → label "Session", pct 47.
# Ollama renders decimals ("31.7% used") and an optional " used" suffix.
_LABEL_RE = re.compile(
    r"^(Session|Weekly|Daily|Monthly)\s+usage\s+(\d+(?:\.\d+)?)\s*%\s*(?:used)?\s*$",
    re.IGNORECASE,
)
# Credits plans, inside #usage-credits-breakdown: the remaining monthly balance,
# and the refill line that carries both the cap and the exact reset date.
_LEFT_RE = re.compile(r"Monthly credits\s*\$([\d,.]+)", re.IGNORECASE)
_REFILL_RE = re.compile(r"Refills to \$([\d,.]+) on (\w+ \d{1,2}, \d{4})", re.IGNORECASE)


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
            m = _LABEL_RE.match(label_attr.strip())
            if m is None:
                continue
            windows.append(
                UsageWindow(
                    label=_label_for(m.group(1)),
                    pct_used=_clamp(float(m.group(2))),
                    reset_at=_sibling_reset_iso(el),
                )
            )
        if credits := _credits_window(soup):
            windows.append(credits)
        if not windows:
            raise RuntimeError("no usage meters found on ollama dashboard")
        return windows


def _credits_window(soup) -> UsageWindow | None:
    box = soup.find(id="usage-credits-breakdown")
    if box is None:
        return None
    text = box.get_text(" ", strip=True)
    left, refill = _LEFT_RE.search(text), _REFILL_RE.search(text)
    if not (left and refill):
        return None
    try:
        remaining = float(left.group(1).replace(",", ""))
        cap = float(refill.group(1).replace(",", ""))
        # shortcut: date only, read as UTC midnight; may be off by the account's TZ offset.
        reset = datetime.strptime(refill.group(2), "%B %d, %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if cap <= 0:
        return None
    used = max(0.0, cap - remaining)
    return UsageWindow(
        label="30d",
        pct_used=_clamp(used / cap * 100),
        reset_at=reset.strftime("%Y-%m-%dT%H:%M:%SZ"),
        used=round(used, 2),
        limit=cap,
        unit="$",
    )


def _clamp(pct: float) -> int:
    return max(0, min(100, int(round(pct))))


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
