"""Ollama Cloud provider.

URL: https://ollama.com/settings
Anchors on aria-label starting with "Session usage " or "Weekly usage ".
Reset read from sibling element's data-time (ISO 8601).
"""

from __future__ import annotations

from http.cookiejar import CookieJar
import json
import re

from bs4 import BeautifulSoup

from tokenmaxxr.providers.base import Provider, RawHtml, register
from tokenmaxxr.reset import parse_iso_utc
from tokenmaxxr.schema import UsageWindow

DASHBOARD_URL = "https://ollama.com/settings"

# An aria-label like "Session usage 47% used" → label "Session", pct 47.
# Ollama's settings page renders decimals ("31.7% used") and an optional
# " used" suffix, so we accept both.
_LABEL_RE = re.compile(
    r"^(Session|Weekly|Daily|Monthly)\s+usage\s+(\d+(?:\.\d+)?)\s*%\s*(?:used)?\s*$",
    re.IGNORECASE,
)


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
            if not m:
                continue
            kind, pct_str = m.group(1), m.group(2)
            try:
                pct = max(0, min(100, int(round(float(pct_str)))))
            except ValueError:
                continue
            reset_at = _sibling_reset_iso(el)
            windows.append(
                UsageWindow(
                    label=_label_for(kind),
                    pct_used=pct,
                    reset_at=reset_at,
                )
            )
        if not windows:
            # Fall back: data embedded in Next.js payload (data-* props).
            windows.extend(_rows_from_next_payload(raw.text))
        if not windows:
            raise RuntimeError("no usage aria-labels found on ollama settings")
        return windows


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


def _rows_from_next_payload(html: str) -> list[UsageWindow]:
    """Ollama ships usage data inside the Next.js __NEXT_DATA__ script.
    When the ARIA tree is missing (hydration timing), fall back to that.
    """
    import re as _re

    m = _re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, _re.DOTALL
    )
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    out: list[UsageWindow] = []
    # Best-effort: walk the JSON looking for {kind, pct, reset_at}-shaped dicts.
    def walk(node):
        if isinstance(node, dict):
            kind = node.get("kind") or node.get("window") or node.get("name")
            pct = node.get("pct_used") or node.get("pct")
            reset = node.get("reset_at") or node.get("resetTime")
            if isinstance(kind, str) and isinstance(pct, (int, float)):
                out.append(
                    UsageWindow(
                        label=_label_for(kind),
                        pct_used=max(0, min(100, int(pct))),
                        reset_at=parse_iso_utc(reset) if isinstance(reset, str) else None,
                    )
                )
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return out


register(OllamaCloudProvider.slug, OllamaCloudProvider)
