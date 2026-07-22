## Context

Greenfield repo (`~/z/tokenmaxxr`, currently only `openspec/`). The user subscribes to three AI coding services — OpenCode Go ($10/mo), ClinePass ($9.99/mo), Ollama Cloud — and wants one place to see quota usage. Investigation on 2026-07-22 established:

- **No official usage APIs exist.** OpenCode (anomalyco/opencode#18648) and Ollama (ollama/ollama#15663) both closed feature requests without shipping an endpoint; ClinePass documents dashboard-only usage. Web-scraping with a session cookie is the only path.
- **Inference credentials don't work for usage.** The API keys/OAuth tokens in `~/.local/share/opencode/auth.json` and `~/.config/pi/agent/auth.json` authenticate chat-completions calls only. Usage data lives behind the web dashboard session cookie.
- **Prior art exists for 2 of 3 providers.** `dzackgarza/usage-limits` (Python) has working OpenCode Go and Ollama Cloud scrapers; `~hrbrmstr/ollama-usage` (Go) has another Ollama one. ClinePass has no published scraper, but its selectors were verified from a real dashboard dump.
- **The user's browser is Zen (Firefox fork) via Flatpak.** Verified live cookies for all three target domains in `~/.var/app/app.zen_browser.zen/.zen/skn3ylbm.Default (release)/cookies.sqlite` (plaintext SQLite — no keychain dance).

Downstream consumers already queued: Waybar (exec + JSON), fastfetch custom module (exec one-liner), and "other people's Java/Python/Go/TS projects" — which all collapse into one requirement: a stable, versioned JSON contract plus exec/HTTP access.

## Goals / Non-Goals

**Goals:**
- One Python engine that scrapes all three dashboards and normalizes to a versioned JSON schema (`schema: 1`).
- Browser-agnostic cookie resolution: works on Zen/Firefox/Chromium/Flatpak variants without per-browser code forks; headless override via `--cookie-file`/env.
- Cache-by-default (TTL 300s) with explicit `--refresh`; stale-fallback when a fetch fails; failure-tolerant per provider (one provider's breakage never blocks the others).
- Append-only `history.jsonl` so the WebUI can graph trends without a database.
- CLI with human table + `--json`; `doctor` command for auth diagnostics.
- Optional `tokenmaxxr serve` (FastAPI) + vanilla-JS WebUI (single `index.html` + `styles.css` + `app.js` served from `tokenmaxxr/_webui/dist/`, no build step) with opt-in auto-refresh and canvas2D history graphs. See `specs/web-dashboard/spec.md` for the rejection note on the Vite + React + shadcn/ui + TanStack Query + Recharts stack.
- Ship as a PyPI package runnable via `uvx tokenmaxxr`.

**Non-Goals:**
- Per-language SDKs (Java/Go/TS). The JSON contract + CLI exec + HTTP API covers them.
- A Go static CLI binary (deferred until a real consumer needs it).
- Historical backfill, a real database, pruning/compaction of `history.jsonl` (revisit when it's actually big).
- Auto-refresh as default behavior in the WebUI (opt-in only).
- Notifications/alerting (ntfy, email) — usage-limits does this; we don't, yet.
- Multi-account per provider (one cookie set per domain).

## Decisions

### D1: One Python engine + JSON contract, not N SDKs

The "reusable for other people" requirement is satisfied by a **stable versioned output schema** consumed via `--json` (exec) or HTTP — not by writing the scraper in four languages. Scraper markup churns; one codebase to fix beats four.

- Alternatives considered: 4 SDKs (rejected — 4× maintenance on the fragile part); Go CLI reimplementation now (rejected — parallel experiment on an unstabilized schema; revisit post-1.0 if static-binary demand appears).

### D2: CLI is Python, not Go/Rust

`tokenmaxxr` is a console-script entry point of the core package. The CLI is a thin formatter over `fetch()` output; putting it in the same language as the engine removes an entire sync surface. Static-binary distribution is a "later" port of a stabilized schema.

### D3: Cookie resolution chain (custom thin resolver over browser_cookie3)

Per provider domain, resolve cookies in order:
1. `--cookie-file <path>` / `TOKENMAXXR_COOKIE_<PROVIDER>` env (headless/servers).
2. Firefox-family stores, globbed: `~/.mozilla/firefox/*`, `~/.zen/*`, `~/.var/app/app.zen_browser.zen/.zen/*`, `~/.var/app/org.mozilla.firefox/...`, floorp/librewolf/waterfox equivalents → `cookies.sqlite` (plaintext).
3. Chromium-family via `browser_cookie3` (needs unlocked libsecret keyring — best-effort).
4. No match → provider status `no-auth`; `doctor` prints remediation.

Always **copy `cookies.sqlite` to a temp file before reading** (WAL lock conflicts with a running browser). browser_cookie3 doesn't know Zen's Flatpak path, so we glob ourselves and hand it paths.

- Alternatives considered: pure browser_cookie3 (rejected — misses Zen Flatpak, the user's actual setup); Playwright/selenium automation (rejected — heavyweight, brittle, and unnecessary when the cookie store is readable).

### D4: Per-provider scrapers behind a common interface

```python
class Provider(Protocol):
    slug: str
    def fetch_raw(self, cookies: CookieJar) -> RawHtml: ...
    def to_rows(self, raw: RawHtml) -> list[UsageWindow]: ...
```

Anchor on **semantic HTML** (ARIA roles/labels, `data-slot`, `data-time`) rather than utility classes:

| Provider | URL | Anchor | pct | reset |
|---|---|---|---|---|
| opencode-go | `opencode.ai/workspace/{id}/go` (id via `/auth` redirect) | `[data-slot=usage-item]` | `[data-slot=usage-value]` | `[data-slot=reset-time]` rel. text |
| clinepass | `app.cline.bot/dashboard/subscription?personal=true` | `[role=progressbar][aria-label$=" usage"]` | `@aria-valuenow` | sibling "Resets in…" rel. text |
| ollama-cloud | `ollama.com/settings` | `[aria-label^="Session usage "]/["Weekly usage "]` | aria-label text | sibling `[data-time]` ISO |

Relative reset strings parse to absolute UTC (`now + delta`) at fetch time.

### D5: Cache = latest-value JSON; history = separate JSONL

```
~/.local/state/tokenmaxxr/
├── cache/<provider>.json     # {fetched_at, payload}; TTL 300s; --refresh deletes first
└── history.jsonl             # {"ts","provider","window","pct_used"} per window per fetch
```

Cache answers "what's the number now" fast; history answers "how did it trend". On fetch failure within TTL: serve stale cache and mark provider `stale`. On failure with no cache: status `error` (or `no-auth` for cookie problems). Never let one provider's failure poison the others' output.

### D6: WebUI = `tokenmaxxr serve` hosting a vanilla-JS single page

FastAPI serves `GET /api/usage` (schema:1 JSON), `GET /api/history?provider=&window=`, `POST /api/refresh`, and statics from `tokenmaxxr/_webui/dist/`. The frontend is a single `index.html` + `styles.css` + `app.js` — no build step, no `node_modules`. The history chart is a hand-rolled canvas2D line plot. This keeps one process owning cache+history — no dual-write consistency problem. Opt-in 60s auto-refresh via a manual toggle button.

- Alternatives considered: Vite + React + shadcn/ui + TanStack Query + Recharts (rejected 2026-07-22 — dashboard is one route with three data sources, the JSON contract is the only real API surface, and pulling in a build pipeline + node_modules would add a JS toolchain the project otherwise does not need). See `openspec/changes/add-quota-aggregator/specs/web-dashboard/spec.md` for the spec-side rejection note and the threshold for revisiting.

- Revisit if any of: a second route appears, the chart requirements exceed what canvas2D can draw, or vanilla-JS component complexity crosses ~500 lines. At that point Recharts + TanStack Query is the preferred upgrade path.

## Risks / Trade-offs

- Vendor redesigns dashboard markup → scraper breaks. → Semantic anchors (D4) reduce frequency; per-provider isolation means one breakage ≠ total outage; `error` status is explicit in output; prior-art repos act as an early-warning canary.
- Session cookie expires/revoked → provider can't fetch. → Status becomes `no-auth`; `doctor` names the exact missing domain; re-login in the browser fixes it with zero config changes.
- Cookie extraction touches sensitive data → misuse risk. → Read-only, copy-before-read, cookies only ever sent to their own domain over HTTPS; cache/history contain only percentages/timestamps, never credentials.
- Chromium keyring locked → Chromium path fails silently. → Expected; chain order prefers Firefox-family (plaintext), and `doctor` reports which stores were readable.
- Scraping may violate ToS. → Accepted: read-only, low-frequency (TTL-gated), same data the user sees in their own dashboard; both prior-art projects operate the same way.
- Relative reset-time parsing is locale/fragile → wrong reset_at. → Ollama gives ISO via `data-time` (parse that preferentially); others get a regex over "Resets in Nd Nh Nm" with unit tests against the captured dump.

## Migration Plan

Greenfield — no migration. Rollout: implement core → CLI → serve/WebUI in the order given in `tasks.md`. Rollback is `pip uninstall`; all state lives under `~/.local/state/tokenmaxxr/` and is safe to delete.

## Open Questions

- Exact Zen non-Flatpak Linux path (`~/.zen` vs XDG data dir) — glob both; only Flatpak verified so far.
