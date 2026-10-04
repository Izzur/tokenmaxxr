"""OpenCode Go provider.

URL: https://opencode.ai/workspace/{workspace_id}/go
Workspace id is auto-discovered via the /auth redirect when missing.
"""

from __future__ import annotations

from http.cookiejar import CookieJar
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from tokenmaxxr.providers.base import Provider, RawHtml, register
from tokenmaxxr.reset import parse_relative_to_utc
from tokenmaxxr.schema import UsageWindow

DASHBOARD_URL = "https://opencode.ai/workspace/{ws}/go"
AUTH_URL = "https://opencode.ai/auth"


def _discover_workspace(sess) -> str:
    """Hit /auth and follow the redirect to find a wrk_-prefixed workspace."""
    r = sess.get(AUTH_URL, allow_redirects=True, timeout=15)
    for url in [r.url, *(h.url for h in r.history)]:
        path = urlparse(url).path
        for seg in path.split("/"):
            if seg.startswith("wrk_"):
                return seg
    # Fall back to the final path segment
    last = urlparse(r.url).path.rstrip("/").split("/")[-1]
    if last:
        return last
    raise RuntimeError("could not discover opencode workspace id")


class OpencodeGoProvider:
    slug = "opencode-go"
    name = "OpenCode Go"
    cookie_domain = "opencode.ai"

    def fetch_raw(self, cookies: CookieJar) -> RawHtml:
        from tokenmaxxr.providers.base import make_session

        sess = make_session(cookies)
        ws = _discover_workspace(sess)
        r = sess.get(DASHBOARD_URL.format(ws=ws), timeout=20)
        r.raise_for_status()
        return RawHtml(url=r.url, text=r.text)

    def to_rows(self, raw: RawHtml) -> list[UsageWindow]:
        soup = BeautifulSoup(raw.text, "html.parser")
        windows: list[UsageWindow] = []
        for item in soup.select('[data-slot="usage-item"]'):
            label_text = (
                item.select_one('[data-slot="usage-label"]').get_text(strip=True)
                if item.select_one('[data-slot="usage-label"]')
                else ""
            )
            value_el = item.select_one('[data-slot="usage-value"]')
            reset_el = item.select_one('[data-slot="reset-time"]')
            pct = _parse_pct(value_el.get_text(" ", strip=True) if value_el else "")
            if pct is None:
                continue
            windows.append(
                UsageWindow(
                    label=_label_for(label_text),
                    pct_used=pct,
                    reset_at=parse_relative_to_utc(
                        reset_el.get_text(" ", strip=True) if reset_el else ""
                    ),
                )
            )
        if not windows:
            raise RuntimeError("no usage-item elements found on opencode dashboard")
        return windows


def _label_for(text: str) -> str:
    t = text.lower()
    if "rolling" in t or "5h" in t or "5 hour" in t:
        return "5h"
    if "weekly" in t or "7d" in t or "week" in t:
        return "7d"
    if "monthly" in t or "30d" in t or "month" in t:
        return "30d"
    return text.strip() or "?"


def _parse_pct(text: str) -> int | None:
    s = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    if not s:
        return None
    try:
        n = int(float(s))
    except ValueError:
        return None
    return max(0, min(100, n))


register(OpencodeGoProvider.slug, OpencodeGoProvider)
