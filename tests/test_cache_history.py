"""Cache + history semantics."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from tokenmaxxr import cache, history
from tokenmaxxr.schema import ProviderResult, UsageWindow


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    return tmp_path


def _r(label="5h", pct=10, reset_at=None):
    return ProviderResult(
        id="opencode-go",
        name="OpenCode Go",
        status="ok",
        windows=[UsageWindow(label=label, pct_used=pct, reset_at=reset_at)],
    )


def test_fresh_cache_hit(isolated):
    cache.write("opencode-go", _r(pct=42))
    hit = cache.read("opencode-go")
    assert hit is not None
    assert hit.windows[0].pct_used == 42


def test_ttl_miss(isolated, monkeypatch):
    cache.write("opencode-go", _r(pct=1))
    p = cache._path_for("opencode-go")  # type: ignore[attr-defined]
    # Rewrite fetched_at to 1 hour ago.
    data = json.loads(p.read_text())
    old = datetime.now(timezone.utc).timestamp() - 3600
    data["fetched_at"] = (
        datetime.fromtimestamp(old, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    p.write_text(json.dumps(data))
    assert cache.read("opencode-go", ttl=60) is None


def test_refresh_invalidates(isolated):
    cache.write("opencode-go", _r(pct=1))
    cache.invalidate("opencode-go")
    assert cache.read("opencode-go") is None


def test_stale_fallback_returns_cached(isolated):
    cache.write("opencode-go", _r(pct=77))
    stale = cache.read_any_age("opencode-go")
    assert stale is not None and stale.status == "stale"


def test_history_appends_on_live(isolated):
    history.append(_r(label="5h", pct=11))
    history.append(_r(label="7d", pct=22))
    rows = history.read_all()
    assert len(rows) == 2
    assert rows[0]["provider"] == "opencode-go"
    assert rows[1]["window"] == "7d"


def test_history_filter(isolated):
    history.append(_r(label="5h", pct=1))
    history.append(_r(label="7d", pct=2))
    out = history.read_all(window="7d")
    assert len(out) == 1 and out[0]["window"] == "7d"


def test_history_compact_drops_old_and_repeats(isolated):
    """Keeps the first in-range line per provider/window, then only changes."""
    lines = [
        ("2026-07-01T00:00:00Z", "5h", 5),   # older than 90d: dropped
        ("2026-10-01T00:00:00Z", "5h", 5),   # first in range: kept
        ("2026-10-01T00:05:00Z", "5h", 5),   # repeat: dropped
        ("2026-10-01T00:05:00Z", "7d", 5),   # other window: kept
        ("2026-10-01T00:10:00Z", "5h", 9),   # change: kept
        ("2026-10-01T00:15:00Z", "5h", 5),   # change back: kept
    ]
    path = cache.history_path()
    path.write_text(
        "".join(json.dumps({"ts": t, "provider": "opencode-go", "window": w, "pct_used": p}) + "\n"
                for t, w, p in lines) + "not json\n"
    )
    history.compact(now=datetime(2026, 11, 7, tzinfo=timezone.utc))
    got = [(r["ts"], r["window"], r["pct_used"]) for r in history.read_all()]
    assert got == [lines[1], lines[3], lines[4], lines[5]]


def test_history_append_compacts_past_max_bytes(isolated, monkeypatch):
    monkeypatch.setattr(history, "MAX_BYTES", 0)
    for _ in range(3):
        history.append(_r(pct=7))
    assert len(history.read_all()) == 1
