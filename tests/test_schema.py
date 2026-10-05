"""Schema:1 contract."""

import json

from tokenmaxxr.schema import ProviderResult, UsageWindow, build_document, dumps


def test_schema_version_and_keys():
    doc = build_document([
        ProviderResult(
            id="clinepass",
            name="ClinePass",
            status="ok",
            windows=[UsageWindow(label="5h", pct_used=12, reset_at="2026-07-22T20:00:00Z")],
        ),
        ProviderResult(id="opencode-go", name="OpenCode Go", status="no-auth"),
        ProviderResult(id="ollama-cloud", name="Ollama Cloud", status="error", error="boom"),
    ])
    assert doc["schema"] == 1
    assert doc["fetched_at"].endswith("Z")
    assert {p["id"] for p in doc["providers"]} == {"clinepass", "opencode-go", "ollama-cloud"}
    assert doc["providers"][1]["status"] == "no-auth"
    assert "error" in doc["providers"][2]


def test_dumps_is_valid_json():
    doc = build_document([ProviderResult(id="x", name="x")])
    parsed = json.loads(dumps(doc))
    assert parsed == doc


def test_window_amounts_optional():
    """used/limit/unit appear only when set; reset_at always present."""
    doc = build_document([ProviderResult(id="x", name="x", windows=[
        UsageWindow(label="5h", pct_used=1, reset_at=None),
        UsageWindow(label="30d", pct_used=2, reset_at=None, used=1.5, limit=60, unit="$"),
    ])])
    plain, money = doc["providers"][0]["windows"]
    assert plain == {"label": "5h", "pct_used": 1, "reset_at": None}
    assert money == {"label": "30d", "pct_used": 2, "reset_at": None, "used": 1.5, "limit": 60, "unit": "$"}
