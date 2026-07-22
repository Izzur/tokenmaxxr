## Why

Checking quota usage for three AI subscriptions (OpenCode Go, ClinePass, Ollama Cloud) means opening three different web dashboards by hand. None of the providers exposes an official usage/quota API (confirmed: anomalyco/opencode#18648 closed without an endpoint, ollama/ollama#15663 closed without an endpoint, ClinePass documents dashboard-only usage), so the data has to be scraped from the dashboards with a browser session cookie. tokenmaxxr centralizes that scrape behind one engine, one versioned JSON contract, and a CLI/WebUI on top.

## What Changes

- New Python core package (`core/tokenmaxxr/`): provider plugins that fetch and parse usage HTML, normalize results into a versioned JSON schema (`schema: 1`), and persist results.
- Three providers: `opencode-go`, `clinepass`, `ollama-cloud` (ClinePass selectors verified against a real dashboard dump; the other two crib from published prior art).
- Browser-agnostic cookie resolution chain: explicit `--cookie-file`/env override → glob of Firefox-family stores (incl. Zen Flatpak paths) → Chromium-family best-effort → `no-auth` status with doctor hint. Cookies are copied to a temp file before reading (WAL lock on running browsers).
- Per-provider TTL cache (default 300s) as JSON files under `~/.local/state/tokenmaxxr/cache/`; `--refresh` bypasses the cache. Failures fall back to stale cache when available.
- Append-only history log `~/.local/state/tokenmaxxr/history.jsonl` written on every successful fetch (drives WebUI graphs).
- `tokenmaxxr` CLI: human table output (default) and `--json` (the stable contract for Waybar/fastfetch/any consumer), plus `tokenmaxxr doctor` (profile + per-domain cookie presence report).
- Optional `tokenmaxxr serve`: FastAPI server exposing the JSON contract + history, serving the WebUI build.
- Vanilla-JS WebUI (`tokenmaxxr/_webui/dist/`): single `index.html` + `styles.css` + `app.js` (no build step, no `node_modules`); opt-in auto-refresh via a manual toggle, history graphs hand-rolled on canvas2D. See `specs/web-dashboard/spec.md` for the rejection note on Vite + React + shadcn/ui + TanStack Query + Recharts and the threshold for revisiting that stack.
- Distribution via PyPI/`uvx tokenmaxxr`. No per-language SDKs — other languages consume the JSON contract or exec the CLI.

## Capabilities

### New Capabilities
- `usage-collection`: Provider plugins that authenticate via resolved browser cookies, fetch usage dashboards, parse them into normalized usage windows (label, pct_used, reset_at), and surface per-provider status (`ok`/`stale`/`error`/`no-auth`).
- `usage-caching`: TTL cache of the latest fetch per provider, force-refresh bypass, stale-fallback on fetch failure, and append-only history logging of successful fetches.
- `cli-output`: The `tokenmaxxr` command — table and `--json` output of the versioned schema, `--refresh`, per-provider selection, and the `doctor` diagnostics command.
- `web-dashboard`: Optional `tokenmaxxr serve` HTTP API (current usage + history) and the vanilla-JS WebUI with opt-in auto-refresh and canvas2D history graphs.

### Modified Capabilities
<!-- None — greenfield repo, no existing specs. -->

## Impact

- **Code**: greenfield repo; adds `core/`, `cli` entry point, `web/`, `openspec/` artifacts.
- **Dependencies (core)**: `requests`, `beautifulsoup4`, `browser_cookie3`, `fastapi`+`uvicorn` (serve only). Web: zero — single static page served from `tokenmaxxr/_webui/dist/`, no build toolchain.
- **Data**: writes only under `~/.local/state/tokenmaxxr/` (cache + history). Reads browser cookie stores (copy-before-read, never mutates).
- **Security**: reads sensitive session cookies locally; never transmits them anywhere except the owning provider's domain over HTTPS. `history.jsonl` and cache contain only percentages/timestamps — no credentials.
- **Consumers**: Waybar (exec + JSON), fastfetch custom module (exec one-liner), any language via `--json` or the HTTP API.
- **Fragility (accepted)**: scrapers depend on vendor dashboard markup; a redesign degrades one provider to `error` status without affecting others.
