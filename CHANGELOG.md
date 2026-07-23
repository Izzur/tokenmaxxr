# Changelog

All notable changes to this project are documented here.
This project follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

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