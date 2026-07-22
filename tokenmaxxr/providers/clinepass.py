"""ClinePass provider.

URL: https://app.cline.bot/dashboard/subscription?personal=true
Anchors on progressbar elements with aria-label ending " usage".
"""

from __future__ import annotations

from http.cookiejar import CookieJar

from bs4 import BeautifulSoup, Tag

from tokenmaxxr.providers.base import Provider, RawHtml, register
from tokenmaxxr.reset import parse_relative_to_utc
from tokenmaxxr.schema import UsageWindow

DASHBOARD_URL = (
    "https://app.cline.bot/dashboard/subscription?personal=true"
)


class ClinePassProvider:
    slug = "clinepass"
    name = "ClinePass"
    cookie_domain = "app.cline.bot"

    def fetch_raw(self, cookies: CookieJar) -> RawHtml:
        from tokenmaxxr.providers.base import make_session

        sess = make_session(cookies)
        r = sess.get(DASHBOARD_URL, timeout=20)
        r.raise_for_status()
        return RawHtml(url=r.url, text=r.text)

    def to_rows(self, raw: RawHtml) -> list[UsageWindow]:
        soup = BeautifulSoup(raw.text, "html.parser")
        # Each usage card is a <div> that contains both an <h3> title
        # ("5-Hour Limit" / "Weekly Limit" / "Monthly Limit") and a
        # role="progressbar". Anchor on the semantic structure — both
        # elements must be present — so this stays correct even if
        # Tailwind class names drift.
        cards = soup.find_all(
            lambda tag: (
                getattr(tag, "name", None) == "div"
                and tag.find("h3") is not None
                and tag.find(attrs={"role": "progressbar"}) is not None
            )
        )
        windows: list[UsageWindow] = []
        for card in cards:
            bar = card.find(
                attrs={"role": "progressbar", "aria-label": True}
            )
            if bar is None:
                continue
            label = (bar.get("aria-label") or "").strip()
            if not label.endswith(" usage"):
                continue
            now = bar.get("aria-valuenow")
            try:
                pct = int(float(now))
            except (TypeError, ValueError):
                continue
            pct = max(0, min(100, pct))
            reset = _card_reset_text(card)
            windows.append(
                UsageWindow(
                    label=_label_for(label),
                    pct_used=pct,
                    reset_at=parse_relative_to_utc(reset) if reset else None,
                )
            )
        if not windows:
            raise RuntimeError("no progressbar usage elements on clinepass dashboard")
        return windows


def _card_reset_text(card: Tag) -> str | None:
    """Return the "Resets in …" text inside a single card, or None.

    The dump structure puts the "Resets in …" text inside a <p> sibling of the
    progressbar's <div> parent. Search the card subtree for any <p> that starts
    with "Resets in" — this scopes to the current card without bleeding into
    sibling cards.
    """
    for p in card.find_all("p"):
        txt = p.get_text(" ", strip=True)
        if txt.lower().startswith("resets in"):
            return txt
    for div in card.find_all("div"):
        txt = div.get_text(" ", strip=True)
        if (
            txt.lower().startswith("resets in")
            and len(txt) < 80
            and div.find("p") is None
        ):
            return txt
    return None


def _label_for(label: str) -> str:
    t = label.lower()
    if "5-hour" in t or "5 hour" in t or "5h" in t:
        return "5h"
    if "weekly" in t or "week" in t:
        return "7d"
    if "monthly" in t or "month" in t:
        return "30d"
    return label or "?"


register(ClinePassProvider.slug, ClinePassProvider)
