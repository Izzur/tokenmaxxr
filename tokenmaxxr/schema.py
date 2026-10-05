"""Schema:1 — the versioned JSON contract.

Single source of truth for what `tokenmaxxr --json` emits and what
`GET /api/usage` returns. Bump SCHEMA on breaking changes; bump the
major version of the package and add a spec delta.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Literal

SCHEMA: int = 1
Status = Literal["ok", "stale", "error", "no-auth"]


@dataclass(frozen=True)
class UsageWindow:
    label: str  # canonical: "5h", "7d", "30d"
    pct_used: int  # 0..100
    reset_at: str | None  # ISO 8601 UTC, or None if unknown
    # Optional absolute amounts when the provider reports them. unit is "$"
    # for dollars, else a plural noun ("credits"). Omitted from JSON if None.
    used: float | None = None
    limit: float | None = None
    unit: str | None = None


def window_dict(w: UsageWindow) -> dict[str, Any]:
    d = asdict(w)
    return {k: v for k, v in d.items() if v is not None or k == "reset_at"}


@dataclass
class ProviderResult:
    id: str
    name: str
    status: Status = "ok"
    windows: list[UsageWindow] = field(default_factory=list)
    error: str | None = None  # populated when status is error


def build_document(
    providers: Iterable[ProviderResult],
    *,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the schema:1 JSON document.

    Returned shape: {"schema": 1, "fetched_at": "<iso>", "providers": [...]}.
    """
    ts = (fetched_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "schema": SCHEMA,
        "fetched_at": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "providers": [
            {
                "id": p.id,
                "name": p.name,
                "status": p.status,
                "windows": [window_dict(w) for w in p.windows],
                **({"error": p.error} if p.error else {}),
            }
            for p in providers
        ],
    }


def dumps(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, sort_keys=False)


def status_of(*, has_cookies: bool, ok: bool, had_cache: bool) -> Status:
    """Derive provider status from cookie + fetch outcome + cache presence."""
    if not has_cookies:
        return "no-auth"
    if ok:
        return "ok"
    return "stale" if had_cache else "error"
