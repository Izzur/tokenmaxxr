## 1. Project scaffold

- [x] 1.1 Create `core/` package layout (`tokenmaxxr/` with `providers/`, `cookies.py`, `cache.py`, `history.py`, `schema.py`, `cli.py`) and `pyproject.toml` (console script `tokenmaxxr`, extras `[serve]` for fastapi+uvicorn)
- [x] 1.2 Add dependencies: requests, beautifulsoup4, browser_cookie3; dev: pytest
- [x] 1.3 Define schema:1 types in `schema.py` (UsageWindow, ProviderResult, document builder with `schema`/`fetched_at`/`providers`) — single source of truth for the JSON contract

## 2. Cookie resolution

- [x] 2.1 Implement override layer: `--cookie-file` / `TOKENMAXXR_COOKIE_<PROVIDER>` env
- [x] 2.2 Implement Firefox-family store discovery: glob `~/.mozilla/firefox/*`, `~/.zen/*`, `~/.var/app/app.zen_browser.zen/.zen/*`, `~/.var/app/org.mozilla.firefox/.mozilla/firefox/*`, floorp/librewolf/waterfox; copy `cookies.sqlite` to temp before querying (WAL-safe)
- [x] 2.3 Implement Chromium-family discovery via browser_cookie3, wrapped in try/except (locked keyring → skip silently)
- [x] 2.4 Chain resolution (override → firefox-family → chromium → `no-auth`) with a `resolve(domain) -> CookieJar | None` API; never write to browser stores
- [x] 2.5 Tests: fixture sqlite with target-domain cookies, override precedence, missing-everywhere → None

## 3. Providers

- [x] 3.1 Provider protocol/base: `slug`, `name`, `fetch_raw(cookies)`, `to_rows(raw)`, status normalization
- [x] 3.2 opencode-go: workspace-id discovery via `/auth` redirect; parse `[data-slot=usage-item]` → label/value/reset (Rolling→5h, Weekly→7d, Monthly→30d); relative reset text → UTC
- [x] 3.3 clinepass: parse `[role=progressbar][aria-label$=" usage"]` → `@aria-valuenow`; sibling "Resets in…" → UTC; unit test against the captured dump (`/tmp/clinepass.html` copied into `tests/fixtures/`)
- [x] 3.4 ollama-cloud: parse `[aria-label^="Session usage "]/["Weekly usage "]`; reset from sibling `[data-time]` ISO
- [x] 3.5 Failure isolation: per-provider try/except → status `error`; cookie absence → `no-auth`; never abort other providers
- [x] 3.6 Tests: fixture HTML per provider (happy path + missing elements), reset-text parser units

## 4. Cache and history

- [x] 4.1 Cache: read/write `~/.local/state/tokenmaxxr/cache/<provider>.json`, TTL 300s, fresh-hit short-circuits fetch
- [x] 4.2 `--refresh` bypass: delete cache entry before fetch
- [x] 4.3 Stale fallback: fetch failure + cache exists → serve cached payload with status `stale`; failure + no cache → `error`
- [x] 4.4 History: append `{ts, provider, window, pct_used}` per window to `history.jsonl` on successful live fetch only (no writes on cache hit or failure)
- [x] 4.5 Tests: TTL boundaries, refresh bypass, stale/error paths, history append semantics

## 5. CLI

- [x] 5.1 `tokenmaxxr` default table output (provider, window, pct, reset; non-ok statuses marked)
- [x] 5.2 `--json` emitting the schema:1 document; `--provider` (repeatable) selection; `--refresh`
- [x] 5.3 `tokenmaxxr doctor`: per-provider cookie-store discovery report, per-domain presence, remediation hints, no cookie values
- [x] 5.4 Tests: JSON contract shape, provider filtering, doctor output redaction
- [x] 5.5 Verify `uvx tokenmaxxr --json` runs from a clean environment

## 6. Serve + WebUI

- [x] 6.1 `tokenmaxxr serve` (extras `[serve]`): `GET /api/usage`, `POST /api/refresh`, `GET /api/history?provider=&window=`; static file serving of `web/dist`; clear error when extras/build missing
- [x] 6.2 Scaffold `web/` (vanilla-JS, no build step — single-page dashboard served from `_webui/dist`)
- [x] 6.3 Dashboard: per-provider cards with windows, pct, reset, status badges; data from `/api/usage`
- [x] 6.4 Opt-in auto-refresh toggle (60s polling, off by default)
- [x] 6.5 History graphs per provider window from `/api/history` (canvas 2D line chart)
- [x] 6.6 Verify in browser: cards render, toggle starts/stops polling, history section appears

## 7. Packaging

- [x] 7.1 PyPI metadata, README (install, Waybar + fastfetch snippets, cookie setup, `--cookie-file` headless example)
- [x] 7.2 Publish workflow (CI matrix on 3.10/3.11/3.12, trusted-publishing release pipeline)
