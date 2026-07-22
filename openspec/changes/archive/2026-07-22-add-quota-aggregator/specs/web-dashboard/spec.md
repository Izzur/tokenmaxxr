## ADDED Requirements

### Requirement: HTTP API server

The system SHALL provide `tokenmaxxr serve`, an HTTP server exposing: `GET /api/usage` (the schema:1 JSON document, honoring the cache), `POST /api/refresh` (force live fetch, same shape), and `GET /api/history` (history entries, filterable by `provider` and `window` query params). The server MUST serve the built WebUI static assets for non-API routes.

#### Scenario: Usage endpoint matches CLI contract
- **WHEN** a client calls `GET /api/usage`
- **THEN** the response body is identical in shape to `tokenmaxxr --json` output

#### Scenario: Refresh endpoint forces live fetch
- **WHEN** a client calls `POST /api/refresh`
- **THEN** providers are fetched live, cache and history are updated, and the fresh document is returned

#### Scenario: History filtering
- **WHEN** a client calls `GET /api/history?provider=clinepass&window=7d`
- **THEN** only history entries for that provider and window are returned

### Requirement: Web dashboard UI

The WebUI SHALL be a single-page application that renders: current usage per provider (from `/api/usage`), per-window history graphs (from `/api/history`), and provider status indicators. Auto-refresh MUST be opt-in (user-toggled polling), never on by default. The implementation MAY use any combination of HTML, CSS, and JavaScript — the spec constrains behavior, not framework choice.

#### Scenario: Dashboard renders all providers
- **WHEN** the user opens the WebUI
- **THEN** each provider's windows are shown with percentage, reset time, and status

#### Scenario: Opt-in auto-refresh
- **WHEN** the user enables auto-refresh
- **THEN** the UI polls the API on an interval; when disabled, no polling occurs

#### Scenario: History graph per window
- **WHEN** the user views a provider's window detail
- **THEN** a graph of pct_used over time is rendered from history data

## Considered alternatives (rejected 2026-07-22)

Earlier drafts specified a Vite + React + shadcn/ui + TanStack Query + Recharts stack. That stack was considered and rejected for the initial release: the dashboard is one route with three data sources, the served JSON contract is the only real API surface, and pulling in a build pipeline + node_modules would add a JS toolchain the project otherwise does not need. The vanilla-JS choice (single `index.html` + `styles.css` + `app.js` served from `tokenmaxxr/_webui/dist/`, no build step, canvas2D for the history chart) is the initial implementation.

Revisit if any of: (a) the dashboard grows a second route, (b) the chart requirements exceed what canvas2D can draw, (c) component complexity (e.g. provider detail drill-down, per-window config) crosses ~500 lines of vanilla JS. At that point, Recharts + TanStack Query is the preferred upgrade path; shadcn/ui + Vite are still preferred for the build harness.

### Requirement: Optional component

The WebUI and server MUST be optional: the core engine and CLI MUST function fully without the web stack installed or built.

#### Scenario: CLI works without web build
- **WHEN** `web/dist` does not exist and FastAPI extras are not installed
- **THEN** `tokenmaxxr` and `tokenmaxxr --json` still work; only `tokenmaxxr serve` reports the missing extras
