"""AWS Kiro provider.

Reads the bearer token kiro-cli already holds in its SQLite state
(`$XDG_DATA_HOME/kiro-cli/data.sqlite3`, default `~/.local/share/kiro-cli/`),
falling back to the Kiro IDE file `~/.aws/sso/cache/kiro-auth-token.json`.
Then calls `AmazonCodeWhispererService.GetUsageLimits` — the same operation
kiro-cli's `/usage` command makes.

Response shape: {"nextDateReset": epoch_s, "subscriptionInfo":
{"subscriptionTitle": "KIRO PRO"}, "usageBreakdownList": [{"resourceType":
"CREDIT", "currentUsageWithPrecision": 40.0, "usageLimitWithPrecision": 100.0,
"freeTrialInfo": {...}?}]}.

Kiro access tokens live ~1h. Rather than re-implementing the OIDC refresh
(and racing kiro-cli for refresh-token rotation), an expired CLI token makes
us run `kiro-cli whoami`, which refreshes and persists the token itself; we
then re-read the db. IDE-file tokens are not refreshed (IDE owns them).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path

from tokenmaxxr.providers.base import NoAuth, RawHtml, make_session, register
from tokenmaxxr.schema import UsageWindow

_TOKEN_KEYS = ("kirocli:social:token", "kirocli:odic:token", "codewhisperer:odic:token")
_PROFILE_KEY = "api.codewhisperer.profile"
_TARGET = "AmazonCodeWhispererService.GetUsageLimits"
_REGION_RE = re.compile(r"^[a-z]{2}(-[a-z0-9]+)+-\d$")


def cli_db_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "kiro-cli" / "data.sqlite3"


def ide_token_path() -> Path:
    return Path(os.path.expanduser("~/.aws/sso/cache/kiro-auth-token.json"))


def load_credential(db: Path | None = None, ide_file: Path | None = None) -> dict:
    """Return {"token", "region", "profile_arn", "expires_at"} from the first source found."""
    db = db or cli_db_path()
    ide_file = ide_file or ide_token_path()
    if db.exists():
        try:
            return _from_sqlite(db)
        except _Expired:
            _refresh_via_cli()
            try:
                return _from_sqlite(db)
            except _Expired as e:
                raise NoAuth(str(e)) from e
    if ide_file.exists():
        return _from_ide_file(ide_file)
    raise NoAuth(f"neither {db} nor {ide_file} found — run `kiro-cli login`")


class _Expired(NoAuth):
    """Token present but past expires_at; caller may try a refresh."""


def _refresh_via_cli() -> None:
    exe = shutil.which("kiro-cli")
    if not exe:
        return
    try:
        # `whoami` loads the token and refreshes it when expired; output unused.
        subprocess.run([exe, "whoami"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _from_sqlite(db: Path) -> dict:
    # ponytail: read-only URI open on kiro-cli's live WAL db. Copy-to-temp
    # (see cookies._copy_db_to_temp) if this ever hits "database is locked".
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise NoAuth(f"cannot open {db}: {e}") from e
    try:
        rows = dict(conn.execute("select key, value from auth_kv").fetchall())
        prof = conn.execute("select value from state where key = ?", (_PROFILE_KEY,)).fetchone()
    except sqlite3.Error as e:
        raise NoAuth(f"cannot read {db}: {e}") from e
    finally:
        conn.close()
    raw = next((rows[k] for k in _TOKEN_KEYS if rows.get(k)), None)
    if not raw:
        raise NoAuth(f"no kiro token in {db} — run `kiro-cli login`")
    tok = json.loads(raw)
    arn = ""
    if prof and prof[0]:
        try:
            arn = (json.loads(prof[0]) or {}).get("arn") or ""
        except ValueError:
            arn = ""
    return _normalize(tok.get("access_token"), tok.get("expires_at"), tok.get("region"), arn)


def _from_ide_file(path: Path) -> dict:
    try:
        tok = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise NoAuth(f"cannot read {path}: {e}") from e
    try:
        return _normalize(tok.get("accessToken"), tok.get("expiresAt"), tok.get("region"), tok.get("profileArn") or "")
    except _Expired as e:
        raise NoAuth(str(e)) from e


def _normalize(token, expires_at, region, arn) -> dict:
    if not token:
        raise NoAuth("kiro credential has no access token — run `kiro-cli login`")
    if expires_at:
        try:
            exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                raise _Expired("Kiro token expired — run any `kiro-cli` command to refresh it")
        except ValueError:
            pass
    # Region: prefer the profile ARN's region (arn:aws:codewhisperer:REGION:...).
    parts = arn.split(":") if arn else []
    if len(parts) >= 4 and parts[2] == "codewhisperer" and parts[3]:
        region = parts[3]
    region = (region or "us-east-1").strip()
    if not _REGION_RE.match(region):
        raise NoAuth(f"kiro credential has an invalid region {region!r}")
    return {"token": token, "region": region, "profile_arn": arn, "expires_at": expires_at}


class KiroProvider:
    slug = "kiro"
    name = "Kiro"
    cookie_domain = None

    def auth_hint(self) -> str:
        for p in (cli_db_path(), ide_token_path()):
            if p.exists():
                return f"{p} (present)"
        return f"{cli_db_path()} missing — run `kiro-cli login`"

    def fetch_raw(self, cookies: CookieJar | None) -> RawHtml:
        cred = load_credential()
        url = f"https://codewhisperer.{cred['region']}.amazonaws.com/"
        sess = make_session(CookieJar())
        sess.headers.update(
            {
                "Authorization": f"Bearer {cred['token']}",
                "Content-Type": "application/x-amz-json-1.0",
                "x-amz-target": _TARGET,
            }
        )
        body = {"origin": "AI_EDITOR", "profileArn": cred["profile_arn"], "resourceType": "AGENTIC_REQUEST"}
        r = sess.post(url, data=json.dumps(body), timeout=20)
        return RawHtml(url=url, text=r.text, usage_status=r.status_code)

    def to_rows(self, raw: RawHtml) -> list[UsageWindow]:
        if raw.usage_status in (401, 403):
            raise NoAuth("Kiro rejected the token — run any `kiro-cli` command to refresh it")
        if raw.usage_status is None or raw.usage_status >= 400:
            raise RuntimeError(f"kiro usage API returned {raw.usage_status}: {raw.text[:200]}")
        try:
            data = json.loads(raw.text)
        except ValueError as e:
            raise RuntimeError(f"kiro usage API returned non-JSON: {e}") from e
        common_reset = _epoch_iso(data.get("nextDateReset"))
        windows: list[UsageWindow] = []
        for item in data.get("usageBreakdownList") or []:
            kind = (item.get("resourceType") or item.get("displayName") or "credit").lower()
            label = "30d" if kind == "credit" else kind
            trial = item.get("freeTrialInfo") or {}
            if trial.get("freeTrialStatus") == "ACTIVE":
                used, limit = _used_limit(trial)
                if limit > 0:
                    windows.append(
                        UsageWindow(
                            label=f"trial-{label}" if label != "30d" else "trial",
                            pct_used=_pct(used, limit),
                            reset_at=_epoch_iso(trial.get("freeTrialExpiry")) or common_reset,
                        )
                    )
            used, limit = _used_limit(item)
            if limit > 0:
                windows.append(
                    UsageWindow(
                        label=label,
                        pct_used=_pct(used, limit),
                        reset_at=_epoch_iso(item.get("nextDateReset")) or common_reset,
                    )
                )
        if not windows:
            raise RuntimeError("kiro usage API returned no usage buckets")
        return windows


def _used_limit(d: dict) -> tuple[float, float]:
    used = d.get("currentUsageWithPrecision", d.get("currentUsage")) or 0
    limit = d.get("usageLimitWithPrecision", d.get("usageLimit")) or 0
    return float(used), float(limit)


def _pct(used: float, limit: float) -> int:
    return max(0, min(100, int(round(used / limit * 100)))) if limit > 0 else 0


def _epoch_iso(v) -> str | None:
    if not isinstance(v, (int, float)):
        return None
    return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


register(KiroProvider.slug, KiroProvider)
