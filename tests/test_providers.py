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


def test_kiro_usage_json():
    raw = RawHtml(
        url="https://codewhisperer.us-east-1.amazonaws.com/",
        text=json.dumps({
            "nextDateReset": 1759276800.0,
            "subscriptionInfo": {"subscriptionTitle": "KIRO PRO"},
            "usageBreakdownList": [{
                "resourceType": "CREDIT",
                "currentUsageWithPrecision": 40.5,
                "usageLimitWithPrecision": 100.0,
                "freeTrialInfo": {"freeTrialStatus": "ACTIVE", "currentUsage": 10, "usageLimit": 50, "freeTrialExpiry": 1759000000},
            }],
        }),
        usage_status=200,
    )
    rows = get_provider("kiro").to_rows(raw)
    by = {w.label: w for w in rows}
    assert set(by) == {"30d", "trial"}
    assert by["30d"].pct_used == 40 and by["30d"].reset_at == "2025-10-01T00:00:00Z"
    assert by["trial"].pct_used == 20 and by["trial"].reset_at == "2025-09-27T19:06:40Z"


def test_kiro_sqlite_credential(tmp_path):
    import sqlite3
    from tokenmaxxr.providers import NoAuth
    from tokenmaxxr.providers.kiro import load_credential
    db = tmp_path / "data.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("create table auth_kv (key text, value text)")
    conn.execute("create table state (key text, value text)")
    conn.execute("insert into auth_kv values (?, ?)", ("kirocli:odic:token", json.dumps({
        "access_token": "AT", "refresh_token": "RT", "expires_at": "2099-01-01T00:00:00Z", "region": "us-east-1"})))
    conn.execute("insert into state values (?, ?)", ("api.codewhisperer.profile", json.dumps({
        "arn": "arn:aws:codewhisperer:eu-west-1:123:profile/x"})))
    conn.commit(); conn.close()
    cred = load_credential(db, tmp_path / "absent.json")
    assert cred["token"] == "AT"
    assert cred["region"] == "eu-west-1"  # ARN region wins over token region
    with pytest.raises(NoAuth):
        load_credential(tmp_path / "nope.sqlite3", tmp_path / "absent.json")


def test_kiro_expired_token_triggers_cli_refresh(tmp_path, monkeypatch):
    import sqlite3
    from tokenmaxxr.providers import kiro
    db = tmp_path / "data.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("create table auth_kv (key text, value text)")
    conn.execute("create table state (key text, value text)")
    conn.execute("insert into auth_kv values (?, ?)", ("kirocli:odic:token", json.dumps({
        "access_token": "OLD", "expires_at": "2000-01-01T00:00:00Z", "region": "us-east-1"})))
    conn.commit(); conn.close()

    def fake_refresh():
        c = sqlite3.connect(db)
        c.execute("update auth_kv set value = ? where key = ?", (json.dumps({
            "access_token": "NEW", "expires_at": "2099-01-01T00:00:00Z", "region": "us-east-1"}), "kirocli:odic:token"))
        c.commit(); c.close()

    monkeypatch.setattr(kiro, "_refresh_via_cli", fake_refresh)
    assert kiro.load_credential(db, tmp_path / "absent.json")["token"] == "NEW"

    # Refresh that changes nothing → NoAuth, not a crash loop.
    monkeypatch.setattr(kiro, "_refresh_via_cli", lambda: None)
    c = sqlite3.connect(db)
    c.execute("update auth_kv set value = ? where key = ?", (json.dumps({
        "access_token": "OLD", "expires_at": "2000-01-01T00:00:00Z", "region": "us-east-1"}), "kirocli:odic:token"))
    c.commit(); c.close()
    with pytest.raises(kiro.NoAuth, match="expired"):
        kiro.load_credential(db, tmp_path / "absent.json")


def test_fetch_all_maps_no_auth(monkeypatch, tmp_path):
    """Token providers with no credential file report no-auth, not error."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr("tokenmaxxr.providers.kiro.ide_token_path", lambda: tmp_path / "none.json")
    from tokenmaxxr import fetch_all
    doc = fetch_all(providers=["claude", "kiro"], refresh=True)
    assert [p["status"] for p in doc["providers"]] == ["no-auth", "no-auth"]

