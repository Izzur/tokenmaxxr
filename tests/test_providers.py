"""Per-provider parser tests against HTML fixtures."""
import importlib
import json
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
    # Clinepass now reads from the JSON API instead of HTML. Feed it the
    # exact shape /api/v1/users/me/plan/usage-limits returns.
    raw = RawHtml(
        url="https://api.cline.bot/api/v1/users/me/plan/usage-limits",
        text=json.dumps({
            "data": {
                "limits": [
                    {"type": "five_hour", "percentUsed": 0, "resetsAt": "2026-07-22T21:00:00Z"},
                    {"type": "weekly", "percentUsed": 84, "resetsAt": "2026-07-23T07:43:10Z"},
                    {"type": "monthly", "percentUsed": 42, "resetsAt": "2026-08-15T07:43:10Z"},
                ]
            },
            "success": True,
        }),
        auth_status=200,
        usage_status=200,
    )
    p = get_provider("clinepass")
    rows = p.to_rows(raw)
    by_label = {w.label: w for w in rows}
    assert set(by_label) == {"5h", "7d", "30d"}
    assert by_label["5h"].pct_used == 0
    assert by_label["7d"].pct_used == 84
    assert by_label["30d"].pct_used == 42
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


def test_claude_usage_json():
    raw = RawHtml(
        url="https://api.anthropic.com/api/oauth/usage",
        text=json.dumps({
            "five_hour": {"utilization": 47.4, "resets_at": "2026-09-06T20:00:00.000000+00:00"},
            "seven_day": {"utilization": 12, "resets_at": "2026-09-10T07:00:00Z"},
            "seven_day_opus": {"utilization": 3, "resets_at": None},
            "extra_usage": {"is_enabled": True, "utilization": 10.0, "used_credits": 5, "monthly_limit": 50},
        }),
        usage_status=200,
    )
    rows = get_provider("claude").to_rows(raw)
    by = {w.label: w for w in rows}
    assert set(by) == {"5h", "7d", "7d-opus", "extra"}
    assert by["5h"].pct_used == 47 and by["5h"].reset_at == "2026-09-06T20:00:00Z"
    assert by["7d-opus"].reset_at is None
    assert by["extra"].pct_used == 10


def test_claude_401_is_no_auth():
    from tokenmaxxr.providers import NoAuth
    with pytest.raises(NoAuth):
        get_provider("claude").to_rows(RawHtml(url="", text="", usage_status=401))


def test_claude_expired_token(tmp_path):
    from tokenmaxxr.providers import NoAuth
    from tokenmaxxr.providers.claude import load_access_token
    p = tmp_path / ".credentials.json"
    p.write_text(json.dumps({"claudeAiOauth": {"accessToken": "x", "expiresAt": 1}}))
    with pytest.raises(NoAuth, match="expired"):
        load_access_token(p)
    p.write_text(json.dumps({"claudeAiOauth": {"accessToken": "x", "expiresAt": 4102444800000}}))
    assert load_access_token(p) == "x"

