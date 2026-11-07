"""Append-only history log of successful live fetches.

Each line: {"ts": <iso utc>, "provider": <slug>, "window": <label>, "pct_used": <int>}.
Writes only on successful LIVE fetch (not cache hit, not stale fallback).
Past MAX_BYTES the file is compacted once: lines older than KEEP_DAYS go, and
so do repeats (same pct_used as the previous kept line of that provider/window).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from tokenmaxxr.cache import history_path
from tokenmaxxr.schema import ProviderResult

MAX_BYTES = 1_000_000
KEEP_DAYS = 90  # 3x the longest window (30d)


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
    if path.stat().st_size > MAX_BYTES:
        compact()


def compact(*, now: datetime | None = None) -> None:
    """Rewrite history without lines older than KEEP_DAYS or repeated pct_used values."""
    path = history_path()
    if not path.exists():
        return
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=KEEP_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    last: dict[tuple, object] = {}
    kept: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            # ts strings share one fixed UTC format, so they compare as times.
            if str(rec.get("ts", "")) < cutoff:
                continue
            key = (rec.get("provider"), rec.get("window"))
            if key in last and last[key] == rec.get("pct_used"):
                continue
            last[key] = rec.get("pct_used")
            kept.append(line if line.endswith("\n") else line + "\n")
    # shortcut: no lock; a line appended by another process during this rewrite
    # is lost. Fine for a once-per-months compaction; lock if history becomes critical.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(kept), encoding="utf-8")
    os.replace(tmp, path)


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
