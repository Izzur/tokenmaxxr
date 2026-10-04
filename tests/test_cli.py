"""CLI / fetch_all integration tests."""

import json
import sys
from io import StringIO

import pytest

from tokenmaxxr import fetch_all
from tokenmaxxr.cli import main
from tokenmaxxr.providers import get_provider
from tokenmaxxr.providers.base import RawHtml
from tokenmaxxr.schema import ProviderResult, UsageWindow


class _FakeProvider:
    slug = "clinepass"
    name = "ClinePass"
    cookie_domain = "app.cline.bot"

    def fetch_raw(self, cookies):
        return RawHtml(url="https://app.cline.bot/", text="<html></html>")

    def to_rows(self, raw):
        return [UsageWindow(label="5h", pct_used=10, reset_at=None)]


@pytest.fixture
def stub_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    def _stub(slug, _provider):
        from tokenmaxxr.providers import base as b
        monkeypatch.setitem(b._REGISTRY, slug, lambda: _provider)
        # Make sure cookies resolve returns None so the live path runs.
        from tokenmaxxr import cookies as ck
        from tokenmaxxr import fetch as ft
        monkeypatch.setattr(ck, "resolve", lambda domain, **kw: (None, None))
        # fetch.py bound `resolve` at import time — patch the local alias too.
        monkeypatch.setattr(ft, "resolve_cookies", lambda domain, **kw: (None, None))

    return _stub


def test_fetch_all_no_auth(stub_provider):
    p = _FakeProvider()
    stub_provider("clinepass", p)
    doc = fetch_all(providers=["clinepass"])
    assert doc["schema"] == 1
    assert doc["providers"][0]["status"] == "no-auth"
    assert doc["providers"][0]["id"] == "clinepass"


def test_json_shape(stub_provider, capsys):
    p = _FakeProvider()
    stub_provider("clinepass", p)
    rc = main(["--provider", "clinepass", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    doc = json.loads(out)
    assert doc["schema"] == 1
    assert "fetched_at" in doc
    assert "providers" in doc


def test_provider_filtering(stub_provider, capsys):
    p = _FakeProvider()
    stub_provider("clinepass", p)
    rc = main(["--provider", "clinepass", "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert [pr["id"] for pr in doc["providers"]] == ["clinepass"]


def test_doctor(stub_provider, monkeypatch, capsys, tmp_path):
    """Shows the store that resolved, live result, config exclusion; never
    cookie values. Exit 1 when a checked provider is not ok."""
    from http.cookiejar import Cookie, CookieJar
    from tokenmaxxr import cookies as ck
    from tokenmaxxr.providers import NoAuth

    stub_provider("clinepass", _FakeProvider())

    class _Broken(_FakeProvider):
        slug, name = "ollama-cloud", "Ollama Cloud"

        def fetch_raw(self, cookies):
            raise NoAuth("session expired")

    stub_provider("ollama-cloud", _Broken())
    jar = CookieJar()
    jar.set_cookie(Cookie(0, "sid", "SECRETVALUE", None, False, "app.cline.bot", True,
                          False, "/", True, True, None, False, None, None, {}))
    src = ck.CookieSource("firefox", "/p/cookies.sqlite", ("app.cline.bot",))
    monkeypatch.setattr(ck, "resolve", lambda domain, **kw: (jar, src))
    monkeypatch.setattr(ck, "discover_sources", lambda domain: [
        src, ck.CookieSource("chromium", "brave", (domain,))
    ])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "tokenmaxxr").mkdir()
    (tmp_path / "tokenmaxxr" / "config.toml").write_text('include = ["clinepass", "ollama-cloud"]\nexclude = ["ollama-cloud"]\n')

    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "auth:  firefox /p/cookies.sqlite (1 cookies)" in out
    assert "also:  chromium brave" in out
    assert "live:  ok  5h:10%" in out
    assert "excluded by config" in out
    assert "SECRETVALUE" not in out

    # Explicit --provider overrides config and surfaces the failure.
    assert main(["--provider", "ollama-cloud", "doctor"]) == 1
    assert "live:  no-auth  session expired" in capsys.readouterr().out
