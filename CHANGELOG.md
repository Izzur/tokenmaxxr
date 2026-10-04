# Changelog

All notable changes to this project are documented here.
This project follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## Unreleased

### Added
- Command Code provider (`commandcode`): uses the `commandcode.ai` browser
  session cookie against `api.commandcode.ai` and reports 5h / 7d spend
  windows plus the 30d monthly credit grant (reset = billing period end).
  DMS pill tag `CC`.
- Ollama Cloud: support the usage-based Pro plan ("Monthly usage $X of $Y
  used"), reported as a 30d window. Legacy 5h / 7d plans still work.

### Changed
- `tokenmaxxr doctor` now live-checks each provider: shows the config file,
  which cookie store or token file is used (plus other candidate stores),
  and the real fetch result or error, bypassing the cache. Honors config
  include/exclude, `--provider` and `--cookie-file`; exits 1 when any
  checked provider is not ok.

### Fixed
- Cookie lookup only probes Chromium-family browsers that have a cookie DB
  on disk, so a locked KDE Wallet no longer pops a "misbehaving app" alert.
- `doctor` no longer lists Firefox profiles that hold no cookies for the
  provider's domain.
- OpenCode Go: workspace discovery crashed on redirects
  (`'Response' object has no attribute 'decode'`).

## 1.1.0 — 2026-09-06

### Added
- Claude provider (`claude`): reads the Claude Code OAuth token from
  `$CLAUDE_CONFIG_DIR/.credentials.json` and reports 5h / 7d / 7d-sonnet /
  7d-opus / extra windows.
- Kiro provider (`kiro`): reads the kiro-cli token from
  `~/.local/share/kiro-cli/data.sqlite3` (or the Kiro IDE file under
  `~/.aws/sso/cache/`) and reports monthly credit usage. An expired CLI
  token triggers `kiro-cli whoami`, which refreshes it in place.
- Token-based providers: `cookie_domain = None` skips cookie discovery;
  new `NoAuth` exception maps to status `no-auth`. `doctor` shows the token
  file path for them.
- Config file `$XDG_CONFIG_HOME/tokenmaxxr/config.toml` with `include`
  (whitelist) / `exclude` (blacklist) provider lists. `--provider` overrides.
- DankMaterialShell bar plugin under `dms/TokenMaxxr/`. Pill shows the
  soonest reset among each provider's longest window; popout shows all.

## 1.0.0 — 2026-07-23

First stable release. Aggregates AI subscription quota usage from three
providers into one versioned JSON document.

### Added
- Three providers: OpenCode Go, ClinePass, Ollama Cloud.
- `tokenmaxxr` CLI — human table (default), `--json` schema:1 document,
  `--refresh` (bypass 300s cache), `--provider` filter (repeatable).
- `tokenmaxxr --version` and `tokenmaxxr.__version__`.
- `tokenmaxxr doctor` — diagnose cookie discovery per provider.
- `tokenmaxxr serve` — FastAPI WebUI + HTTP API on `127.0.0.1:8765`
  (`/api/usage`, `/api/refresh`, `/api/history`, vanilla-JS dashboard).
- Cookie discovery chain: `--cookie-file`/`TOKENMAXXR_COOKIE_*` env →
  Firefox-family stores (Mozilla, Zen, Flatpak Zen, Floorp, LibreWolf,
  Waterfox) → Chromium-family via `browser-cookie3` → `no-auth`.
- WAL-safe cookie reads (temp-file copy), 300s cache, and history
  append under `~/.local/state/tokenmaxxr/`.
- Versioned `schema:1` JSON contract with `ok|stale|no-auth|error` status.
- CI matrix (Python 3.10–3.13), OIDC trusted publishing workflow.

### Fixed
- WebUI dashboard now ships in the wheel (`.gitignore` `dist/` rule was
  excluding `tokenmaxxr/_webui/dist/`; scoped to `/dist/`).