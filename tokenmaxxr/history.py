"""Append-only history log of successful live fetches.

Each line: {"ts": <iso utc>, "provider": <slug>, "window": <label>, "pct_used": <int>}.
Writes only on successful LIVE fetch (not cache hit, not stale fallback).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from tokenmaxxr.cache import history_path
from tokenmaxxr.schema import ProviderResult


def append(result: ProviderResult) -> None:
    """Append one history line per window of `result`."""
    if not result.windows:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = history_path()
    with path.open("a", encoding="utf-8") as fh:
        for w in result.windows:
            fh.write(
                json.dumps(
                    {
                        "ts": ts,
                        "provider": result.id,
                        "window": w.label,
                        "pct_used": w.pct_used,
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )


def read_all(
    *, provider: str | None = None, window: str | None = None
) -> list[dict]:
    path = history_path()
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if provider and rec.get("provider") != provider:
                continue
            if window and rec.get("window") != window:
                continue
            out.append(rec)
    return out
