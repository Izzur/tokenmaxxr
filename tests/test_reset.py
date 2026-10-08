"""Reset-time parser."""

from datetime import datetime, timezone

from tokenmaxxr.reset import parse_iso_utc, parse_relative_to_utc


def test_relative_full():
    base = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
    out = parse_relative_to_utc("Resets in 23 hours 32 minutes", now=base)
    assert out == "2026-07-23T11:32:00Z"


def test_relative_short():
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert parse_relative_to_utc("in 5 days 2 hours", now=base) == "2026-01-06T02:00:00Z"


def test_relative_days_only():
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert parse_relative_to_utc("Resets in 7 days", now=base) == "2026-01-08T00:00:00Z"


def test_relative_unparseable():
    assert parse_relative_to_utc("tomorrow") is None
    assert parse_relative_to_utc("Refills to $60 in 1 month.") is None


def test_iso_utc_z():
    assert parse_iso_utc("2026-07-22T20:00:00Z") == "2026-07-22T20:00:00Z"


def test_iso_utc_offset():
    assert parse_iso_utc("2026-07-22T15:00:00-05:00") == "2026-07-22T20:00:00Z"
