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


def test_ollama_cloud_monthly_budget():
    """Credits plan: one $ budget from the /dashboard credits breakdown."""
    raw = RawHtml(
        url="https://ollama.com/dashboard",
        text=(FIX / "ollama_cloud_monthly.html").read_text(),
    )
    (w,) = get_provider("ollama-cloud").to_rows(raw)
    # "Monthly credits $28.43" + "Refills to $60 on November 18, 2026."
    assert (w.label, w.pct_used, w.used, w.limit, w.unit) == ("30d", 53, 31.57, 60.0, "$")
    assert w.reset_at == "2026-11-18T00:00:00Z"


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
                url="https://opencode.ai/go",
                history=(
                    _Resp("https://opencode.ai/auth"),
                    _Resp("https://opencode.ai/workspace/wrk_abc123"),
                ),
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
    assert (by["30d"].used, by["30d"].limit, by["30d"].unit) == (40.5, 100.0, "credits")
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


def test_config_include_exclude(tmp_path, monkeypatch):
    from tokenmaxxr import config
    known = ["claude", "clinepass", "kiro", "ollama-cloud", "opencode-go"]
    assert config.select_providers(known, {}) == known
    assert config.select_providers(known, {"include": ["kiro", "claude"]}) == ["claude", "kiro"]
    assert config.select_providers(known, {"exclude": ["opencode-go"]}) == known[:-1]
    assert config.select_providers(known, {"include": ["kiro", "claude"], "exclude": ["kiro"]}) == ["claude"]
    with pytest.raises(SystemExit):
        config.select_providers(known, {"include": ["nope"]})
    # File round-trip via XDG_CONFIG_HOME.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "tokenmaxxr").mkdir()
    (tmp_path / "tokenmaxxr" / "config.toml").write_text('exclude = ["opencode-go", "clinepass"]\n')
    assert config.select_providers(known) == ["claude", "kiro", "ollama-cloud"]


def test_commandcode_usage_json():
    raw = RawHtml(
        url="https://api.commandcode.ai/internal/billing/credits",
        text=json.dumps({
            "credits": {
                "credits": {"monthlyCredits": 52.5, "monthlyCreditsGranted": 70},
                "windowLimits": {
                    "limited": True,
                    "fiveHour": {"used": 7.0, "cap": 14, "resetAt": 1789804400302},
                    "weekly": {"used": 3.5, "cap": 35, "resetAt": 1790301251728},
                },
            },
            "subscription": {"currentPeriodEnd": "2026-10-18T01:18:27.000Z"},
        }),
        usage_status=200,
    )
    by = {w.label: w for w in get_provider("commandcode").to_rows(raw)}
    assert set(by) == {"5h", "7d", "30d"}
    assert by["5h"].pct_used == 50 and by["5h"].reset_at == "2026-09-19T07:53:20Z"
    assert by["7d"].pct_used == 10
    assert by["30d"].pct_used == 25 and by["30d"].reset_at == "2026-10-18T01:18:27Z"
    assert (by["5h"].used, by["5h"].limit, by["5h"].unit) == (7.0, 14, "$")
    assert (by["30d"].used, by["30d"].limit, by["30d"].unit) == (17.5, 70, "credits")


def test_commandcode_401_is_no_auth():
    from tokenmaxxr.providers.base import NoAuth
    raw = RawHtml(url="x", text="", usage_status=401)
    with pytest.raises(NoAuth):
        get_provider("commandcode").to_rows(raw)


def test_nous_portal_billing_page():
    """Subscription credits from the RSC payload; the fixture splits that row across two chunks."""
    raw = RawHtml(
        url="https://portal.nousresearch.com/orgs/0a1b2c3d/billing",
        text=(FIX / "nous_portal.html").read_text(),
        usage_status=200,
    )
    (w,) = get_provider("nous-portal").to_rows(raw)
    assert (w.label, w.pct_used, w.used, w.limit, w.unit) == ("30d", 1, 0.17, 22.0, "$")
    assert w.reset_at == "2026-11-18T01:58:10Z"


def test_nous_portal_auth_bounce_is_no_auth():
    """Stale privy-token → /refresh (client-side refresh page); no session at all → /login."""
    from tokenmaxxr.providers.base import NoAuth
    for url in (
        "https://portal.nousresearch.com/refresh?callbackUrl=%2Fbilling&soft=1",
        "https://portal.nousresearch.com/login?callbackUrl=%2Fbilling",
    ):
        with pytest.raises(NoAuth):
            get_provider("nous-portal").to_rows(RawHtml(url=url, text="", usage_status=200))


def test_nous_portal_never_sends_refresh_cookie(monkeypatch):
    """nas-refresh rotates on use; sending the browser's copy would sign the browser out."""
    from http.cookiejar import Cookie, CookieJar
    from types import SimpleNamespace
    from tokenmaxxr.providers import nous_portal

    sent = set()

    def fake_session(jar, user_agent):
        sent.update(c.name for c in jar)
        return SimpleNamespace(get=lambda url, timeout: SimpleNamespace(url=url, text="", status_code=200))

    monkeypatch.setattr(nous_portal, "make_session", fake_session)
    jar = CookieJar()
    for name in ("nas-refresh", "nas-session", "privy-token"):
        jar.set_cookie(Cookie(0, name, "v", None, False, "portal.nousresearch.com", True,
                              False, "/", True, True, None, False, None, None, {}))
    nous_portal.NousPortalProvider().fetch_raw(jar)
    assert sent == {"nas-session", "privy-token"}


def test_nous_portal_account_api():
    """`tokenmaxxr login` path reports the same window as the billing page."""
    from tokenmaxxr.providers import nous_portal
    raw = RawHtml(
        url=nous_portal.ACCOUNT_URL,
        text=json.dumps({"subscription": {
            "plan": "Plus", "monthly_credits": 22, "credits_remaining": 21.8271626847,
            "current_period_end": "2026-11-18T01:58:10.000Z", "rollover_credits": 0,
        }}),
        usage_status=200,
    )
    (w,) = get_provider("nous-portal").to_rows(raw)
    assert (w.label, w.pct_used, w.used, w.limit, w.unit) == ("30d", 1, 0.17, 22.0, "$")
    assert w.reset_at == "2026-11-18T01:58:10Z"


def test_nous_portal_login_and_refresh(monkeypatch, tmp_path, capsys):
    """Device login saves our own 0600 pair; an expiring token is refreshed once with the
    old refresh token and the rotated pair persisted; a dead grant drops the file so the
    cookie path takes over again."""
    from types import SimpleNamespace
    from tokenmaxxr.providers import nous_portal
    from tokenmaxxr.providers.base import NoAuth

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(nous_portal.time, "sleep", lambda s: None)
    replies = [
        (200, {"device_code": "DEVSECRET", "user_code": "ABCD-EFGH", "expires_in": 600, "interval": 5,
               "verification_uri_complete": "https://portal.nousresearch.com/x?user_code=ABCD-EFGH"}),
        (400, {"error": "authorization_pending"}),
        (200, {"access_token": "A1", "refresh_token": "R1", "expires_in": 899}),
        (200, {"access_token": "A2", "refresh_token": "R2", "expires_in": 899}),
        (400, {"error": "refresh_token_reused"}),
    ]
    calls = []

    def post(url, headers=None, data=None, timeout=None):
        calls.append(headers)
        status, body = replies.pop(0)
        return SimpleNamespace(status_code=status, json=lambda: body, raise_for_status=lambda: None)

    monkeypatch.setattr(nous_portal, "_api_session", lambda: SimpleNamespace(post=post, headers={}))
    p = get_provider("nous-portal")
    assert p.cookie_domain == "portal.nousresearch.com"

    nous_portal.login()
    out = capsys.readouterr().out
    assert "ABCD-EFGH" in out and "DEVSECRET" not in out
    path = nous_portal.auth_path()
    assert p.cookie_domain is None and path.stat().st_mode & 0o777 == 0o600
    assert nous_portal._access_token() == "A1" and len(calls) == 3  # still fresh: no refresh

    expired = {**json.loads(path.read_text()), "expires_at": 0}
    path.write_text(json.dumps(expired))
    assert nous_portal._access_token() == "A2"
    assert calls[-1] == {"x-nous-refresh-token": "R1"}
    assert json.loads(path.read_text())["refresh_token"] == "R2"

    path.write_text(json.dumps(expired))
    with pytest.raises(NoAuth):
        nous_portal._access_token()
    assert p.cookie_domain == "portal.nousresearch.com"
