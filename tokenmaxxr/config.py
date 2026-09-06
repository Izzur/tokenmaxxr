"""User config: $XDG_CONFIG_HOME/tokenmaxxr/config.toml (default ~/.config/...).

    include = ["claude", "kiro"]   # whitelist: only these providers
    exclude = ["opencode-go"]      # blacklist: everything except these

Both may be set; include is applied first, then exclude. Missing file or
missing keys = every registered provider.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "tokenmaxxr" / "config.toml"


def load() -> dict:
    p = config_path()
    if not p.exists():
        return {}
    with p.open("rb") as f:
        return tomllib.load(f)


def select_providers(known: list[str], cfg: dict | None = None) -> list[str]:
    """Apply include/exclude from config to the registered slug list."""
    cfg = load() if cfg is None else cfg
    include = cfg.get("include")
    exclude = set(cfg.get("exclude") or [])
    if include:
        unknown = [s for s in include if s not in known]
        if unknown:
            raise SystemExit(f"config include: unknown provider(s) {unknown}; known: {known}")
        known = [s for s in known if s in include]
    return [s for s in known if s not in exclude]
