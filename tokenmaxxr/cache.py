"""Per-provider TTL cache.

Backed by JSON files under $XDG_STATE_HOME/tokenmaxxr/cache/<slug>.json
(defaults to ~/.local/state/tokenmaxxr/cache). Each entry stores
{fetched_at: iso, payload: {...normalized provider result...}}.

`--refresh` is a cache invalidation flag handled by the caller
(tokenmaxxr.fetch), not by this module.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from tokenmaxxr.schema import ProviderResult, UsageWindow, window_dict

DEFAULT_TTL_SECONDS = 300


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser(
        "~/.local/state"
    )
    return Path(base) / "tokenmaxxr"


def cache_dir() -> Path:
    d = state_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def history_path() -> Path:
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "history.jsonl"


def _path_for(slug: str) -> Path:
    safe = slug.replace("/", "_")
    return cache_dir() / f"{safe}.json"


def read(slug: str, *, ttl: int = DEFAULT_TTL_SECONDS) -> ProviderResult | None:
    """Return a fresh cached result, or None on miss / stale."""
    path = _path_for(slug)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    fetched_at = data.get("fetched_at")
    payload = data.get("payload")
    if not isinstance(fetched_at, str) or not isinstance(payload, dict):
        return None
    try:
        ts = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    if age > ttl:
        return None
    return _payload_to_result(slug, payload, status="ok")


def read_any_age(slug: str) -> ProviderResult | None:
    """Return the cached result regardless of age (for stale fallback)."""
    path = _path_for(slug)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return None
    return _payload_to_result(slug, payload, status="stale")


def write(slug: str, result: ProviderResult) -> None:
    path = _path_for(slug)
    payload = {
        "id": result.id,
        "name": result.name,
        "windows": [window_dict(w) for w in result.windows],
    }
    data = {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "payload": payload,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def invalidate(slug: str) -> None:
    path = _path_for(slug)
    if path.exists():
        path.unlink()


def _payload_to_result(
    slug: str, payload: dict, *, status: str
) -> ProviderResult:
    return ProviderResult(
        id=payload.get("id", slug),
        name=payload.get("name", slug),
        status=status,  # type: ignore[arg-type]
        windows=[
            UsageWindow(
                label=w["label"],
                pct_used=int(w["pct_used"]),
                reset_at=w.get("reset_at"),
                used=w.get("used"),
                limit=w.get("limit"),
                unit=w.get("unit"),
            )
            for w in payload.get("windows", [])
            if isinstance(w, dict) and "label" in w and "pct_used" in w
        ],
    )
