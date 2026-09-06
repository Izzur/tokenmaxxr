"""Claude (claude.ai subscription) provider.

Reads the OAuth access token Claude Code already holds in
`$CLAUDE_CONFIG_DIR/.credentials.json` (default `~/.claude/`), then calls
the same usage endpoint the Claude Code `/usage` command uses.

Response shape (2026): {"five_hour": {"utilization": 47.0, "resets_at": iso},
"seven_day": {...}, "seven_day_sonnet": {...}, "seven_day_opus": {...},
"extra_usage": {"is_enabled": bool, "utilization": float, ...}}.

ponytail: no token refresh. Claude Code rotates refresh tokens on use, so
refreshing here could log the user out of Claude Code. Expired token →
NoAuth with a "run `claude`" hint. Add refresh+persist if that gets annoying.
"""

from __future__ import annotations

import json
import os
import time
from http.cookiejar import CookieJar
from pathlib import Path

from tokenmaxxr.providers.base import NoAuth, RawHtml, make_session, register
from tokenmaxxr.reset import parse_iso_utc
from tokenmaxxr.schema import UsageWindow

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

_WINDOWS = (
    ("five_hour", "5h"),
    ("seven_day", "7d"),
    ("seven_day_sonnet", "7d-sonnet"),
    ("seven_day_opus", "7d-opus"),
)


def credentials_path() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return Path(base) / ".credentials.json"


def load_access_token(path: Path | None = None) -> str:
    path = path or credentials_path()
    if not path.exists():
        raise NoAuth(f"{path} not found — run `claude` and log in")
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise NoAuth(f"cannot read {path}: {e}") from e
    oauth = data.get("claudeAiOauth") or {}
    token = oauth.get("accessToken") or data.get("access_token")
    if not token:
        raise NoAuth(f"no accessToken in {path} — run `claude` and log in")
    expires_ms = oauth.get("expiresAt")
    if isinstance(expires_ms, (int, float)) and expires_ms / 1000 < time.time():
        raise NoAuth("Claude token expired — run `claude` once to refresh it")
    return token


class ClaudeProvider:
    slug = "claude"
    name = "Claude"
    cookie_domain = None

    def auth_hint(self) -> str:
        p = credentials_path()
        return f"{p} ({'present' if p.exists() else 'missing — run `claude`'})"

    def fetch_raw(self, cookies: CookieJar | None) -> RawHtml:
        token = load_access_token()
        # User-Agent mirrors Claude Code; the endpoint is gated to that client.
        sess = make_session(CookieJar(), user_agent="claude-code/2.1.69")
        sess.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "anthropic-beta": "oauth-2025-04-20",
            }
        )
        r = sess.get(USAGE_URL, timeout=15)
        return RawHtml(url=USAGE_URL, text=r.text, usage_status=r.status_code)

    def to_rows(self, raw: RawHtml) -> list[UsageWindow]:
        if raw.usage_status in (401, 403):
            raise NoAuth("Claude rejected the token — run `claude` once to refresh it")
        if raw.usage_status is None or raw.usage_status >= 400:
            raise RuntimeError(f"claude usage API returned {raw.usage_status}: {raw.text[:200]}")
        try:
            data = json.loads(raw.text)
        except ValueError as e:
            raise RuntimeError(f"claude usage API returned non-JSON: {e}") from e
        if data.get("type") == "error":
            raise RuntimeError(f"claude usage API error: {data.get('error')}")
        windows: list[UsageWindow] = []
        for key, label in _WINDOWS:
            w = data.get(key)
            if not isinstance(w, dict) or not isinstance(w.get("utilization"), (int, float)):
                continue
            windows.append(
                UsageWindow(
                    label=label,
                    pct_used=_pct(w["utilization"]),
                    reset_at=parse_iso_utc(w.get("resets_at") or ""),
                )
            )
        extra = data.get("extra_usage") or {}
        if extra.get("is_enabled") and isinstance(extra.get("utilization"), (int, float)):
            windows.append(UsageWindow(label="extra", pct_used=_pct(extra["utilization"]), reset_at=None))
        if not windows:
            raise RuntimeError("claude usage API returned no windows")
        return windows


def _pct(v: float) -> int:
    return max(0, min(100, int(round(float(v)))))


register(ClaudeProvider.slug, ClaudeProvider)
