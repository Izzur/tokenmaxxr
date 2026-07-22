# usage-caching Specification

## Purpose
TBD - created by archiving change add-quota-aggregator. Update Purpose after archive.
## Requirements
### Requirement: Per-provider TTL cache

The system SHALL cache the latest successful fetch per provider as a JSON file under `~/.local/state/tokenmaxxr/cache/<provider>.json`, recording the fetch timestamp and the normalized payload. The default TTL MUST be 300 seconds. When a cached entry is younger than the TTL, the system MUST return the cached payload without contacting the provider.

#### Scenario: Cache hit within TTL
- **WHEN** a fetch is requested and a cache entry younger than the TTL exists
- **THEN** the cached payload is returned and no network request is made

#### Scenario: Cache miss after TTL
- **WHEN** a fetch is requested and the cache entry is older than the TTL (or absent)
- **THEN** the provider is fetched live and the cache file is overwritten on success

### Requirement: Force refresh

The system SHALL support a `--refresh` flag (and equivalent API trigger) that bypasses the cache and fetches all selected providers live.

#### Scenario: Refresh bypasses fresh cache
- **WHEN** the user runs with `--refresh` and a fresh cache entry exists
- **THEN** the system fetches live anyway and overwrites the cache on success

### Requirement: Stale fallback on failure

When a live fetch fails and a cache entry exists (of any age), the system SHALL serve the stale cached payload and mark that provider's status as `stale`. When a live fetch fails and no cache exists, the provider's status MUST be `error`.

#### Scenario: Stale data beats no data
- **WHEN** a live fetch raises and a cache entry exists
- **THEN** output shows the cached values with status `stale`

#### Scenario: Failure with no cache
- **WHEN** a live fetch raises and no cache entry exists
- **THEN** the provider reports status `error` and other providers are unaffected

### Requirement: Append-only history log

On every successful live fetch, the system SHALL append one JSON line per usage window to `~/.local/state/tokenmaxxr/history.jsonl`. Each line MUST contain `ts` (fetch time, UTC ISO 8601), `provider`, `window` (label), and `pct_used`. Cache hits MUST NOT write history. The system MUST NOT require a database for history storage.

#### Scenario: History written on live fetch only
- **WHEN** a live fetch of a provider with three windows succeeds
- **THEN** three lines are appended to history.jsonl
- **AND** a subsequent cache-hit fetch appends nothing

#### Scenario: Failed fetch writes no history
- **WHEN** a live fetch fails (serving stale or error)
- **THEN** no lines are appended to history.jsonl for that provider

