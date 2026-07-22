# web-dashboard Specification

## Purpose
TBD - created by archiving change add-quota-aggregator. Update Purpose after archive.
## Requirements
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

