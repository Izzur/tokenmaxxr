"""FastAPI server smoke tests."""

from fastapi.testclient import TestClient


def _client():
    from tokenmaxxr.serve import _build_app
    return TestClient(_build_app())


def test_usage_endpoint():
    r = _client().get("/api/usage")
    assert r.status_code == 200
    body = r.json()
    assert body["schema"] == 1
    assert "providers" in body
    assert isinstance(body["providers"], list)


def test_usage_provider_filter():
    r = _client().get("/api/usage", params={"provider": "clinepass"})
    assert r.status_code == 200
    body = r.json()
    assert [p["id"] for p in body["providers"]] == ["clinepass"]


def test_refresh_endpoint():
    r = _client().post("/api/refresh")
    assert r.status_code == 200
    assert r.json()["schema"] == 1


def test_history_endpoint():
    r = _client().get("/api/history")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
