"""Per-provider parser tests against HTML fixtures."""

import importlib

import pytest

from tokenmaxxr.providers import get_provider
from tokenmaxxr.providers.base import RawHtml

from pathlib import Path

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset_clinepass_registry():
    """Re-import clinepass so test_cli.py's stub_provider doesn't poison us."""
    from tokenmaxxr.providers import clinepass
    importlib.reload(clinepass)
    yield


def test_opencode_go():
    raw = RawHtml(url="https://opencode.ai/workspace/wrk_x/go", text=(FIX / "opencode_go.html").read_text())
    p = get_provider("opencode-go")
    rows = p.to_rows(raw)
    labels = [w.label for w in rows]
    assert labels == ["5h", "7d", "30d"]
    assert rows[0].pct_used == 42
    assert rows[0].reset_at is not None
    assert rows[0].reset_at.endswith("Z")
    assert rows[1].reset_at is not None and rows[1].reset_at.endswith("Z")
    assert rows[2].reset_at is not None and rows[2].reset_at.endswith("Z")


def test_clinepass_real_dump():
    raw = RawHtml(url="https://app.cline.bot/dashboard/subscription", text=(FIX / "clinepass.html").read_text())
    p = get_provider("clinepass")
    rows = p.to_rows(raw)
    by_label = {w.label: w for w in rows}
    assert set(by_label) == {"5h", "7d", "30d"}
    for w in rows:
        assert 0 <= w.pct_used <= 100
        assert w.reset_at is None or w.reset_at.endswith("Z")


def test_ollama_cloud():
    raw = RawHtml(url="https://ollama.com/settings", text=(FIX / "ollama_cloud.html").read_text())
    p = get_provider("ollama-cloud")
    rows = p.to_rows(raw)
    by_label = {w.label: w for w in rows}
    assert set(by_label) == {"5h", "7d"}
    assert by_label["5h"].pct_used == 47
    assert by_label["5h"].reset_at == "2026-07-22T20:00:00Z"


def test_opencode_workspace_discovery():
    """Picks the wrk_-prefixed segment out of the /auth redirect chain."""
    from tokenmaxxr.providers import opencode_go

    class _Resp:
        def __init__(self, url, history=()):
            self.url = url
            self.history = history

    class _Sess:
        def get(self, url, allow_redirects=True, timeout=15):
            return _Resp(
                url="https://opencode.ai/workspace/wrk_abc123/go",
                history=(_Resp("https://opencode.ai/auth"),),
            )

    assert opencode_go._discover_workspace(_Sess()) == "wrk_abc123"


def test_opencode_workspace_discovery_final_segment_fallback():
    """When no wrk_ segment is found, fall back to the final URL's last segment."""
    from tokenmaxxr.providers import opencode_go

    class _Resp:
        def __init__(self, url):
            self.url = url
            self.history = ()

    class _Sess:
        def get(self, url, allow_redirects=True, timeout=15):
            return _Resp("https://opencode.ai/anything/dashboard")

    assert opencode_go._discover_workspace(_Sess()) == "dashboard"
