"""Common helper: parse a "Resets in …" relative string into absolute UTC.

Handles "Resets in 23 hours 32 minutes", "Resets in 5 days", "23h 32m",
"in 1 day 2 hours", and similar variants. Anything we can't parse returns None.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_PATTERN = re.compile(
    r"(\d+)\s*(weeks?|w)|"
    r"(\d+)\s*(days?|d)|"
    r"(\d+)\s*(hours?|hrs?|h)|"
    r"(\d+)\s*(minutes?|mins?|m\b)",  # \b: "1 month" is not 1 minute
    re.IGNORECASE,
)


def parse_relative_to_utc(text: str, *, now: datetime | None = None) -> str | None:
    """Return ISO 8601 UTC string for `now + delta(text)`, or None."""
    if not text:
        return None
    # Strip leading "Resets in " / "in " / "Remaining: " filler
    cleaned = text.strip()
    m = re.search(r"in\s+(.+)$", cleaned, re.IGNORECASE)
    span = m.group(1) if m else cleaned

    delta = timedelta()
    matched = False
    for weeks, _w, days, _d, hours, _h, minutes, _m in _PATTERN.findall(span):
        n = next(int(x) for x in (weeks, days, hours, minutes) if x)
        if weeks:
            delta += timedelta(weeks=n)
        elif days:
            delta += timedelta(days=n)
        elif hours:
            delta += timedelta(hours=n)
        elif minutes:
            delta += timedelta(minutes=n)
        matched = True
    if not matched:
        return None
    base = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return (base + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc(value: str) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
