# cli-output Specification

## Purpose
TBD - created by archiving change add-quota-aggregator. Update Purpose after archive.
## Requirements
### Requirement: Versioned JSON output contract

The CLI SHALL support `--json` producing a stable, versioned JSON document. The document MUST include a top-level `schema` field (integer, currently `1`), `fetched_at` (UTC ISO 8601), and a `providers` array. Each provider entry MUST include `id`, `name`, `status` (`ok`, `stale`, `error`, or `no-auth`), and a `windows` array of `{label, pct_used, reset_at}` objects. The schema version MUST NOT change without a corresponding spec change.

#### Scenario: Machine consumers get stable shape
- **WHEN** any consumer runs `tokenmaxxr --json`
- **THEN** the output parses against the schema:1 contract regardless of which providers succeeded or failed

#### Scenario: Waybar-style consumption
- **WHEN** a consumer extracts `providers[i].windows[0].pct_used` from `--json` output
- **THEN** the value is an integer percentage suitable for direct display

### Requirement: Human table output

By default (no `--json`), the CLI SHALL print a human-readable table listing each provider, its windows, percentage used, and reset time. Providers with non-`ok` status MUST be visibly marked.

#### Scenario: Default invocation prints table
- **WHEN** the user runs `tokenmaxxr` with no flags
- **THEN** a table of all providers' windows is printed, with stale/error/no-auth providers marked

### Requirement: Refresh and provider selection flags

The CLI SHALL support `--refresh` (bypass cache) and a provider-selection option (e.g. `--provider opencode-go`, repeatable) restricting collection to the named providers.

#### Scenario: Single provider query
- **WHEN** the user runs `tokenmaxxr --provider ollama-cloud`
- **THEN** only the ollama-cloud provider is collected and rendered

### Requirement: Doctor diagnostics

The CLI SHALL provide `tokenmaxxr doctor`, which MUST report, for each provider: which cookie stores were discovered, whether cookies for the provider's domain were found, and the remediation step when missing. Doctor MUST NOT print cookie values.

#### Scenario: Missing cookie remediation
- **WHEN** no cookie exists for a provider's domain
- **THEN** doctor names the missing domain and instructs the user to log in via their browser (or use `--cookie-file`)

#### Scenario: Cookie values never shown
- **WHEN** doctor finds valid cookies for all providers
- **THEN** it reports presence only, never cookie contents

### Requirement: Distribution as installable package

The core engine and CLI SHALL be distributed as a single Python package installable from PyPI and runnable via `uvx tokenmaxxr`.

#### Scenario: Run without install
- **WHEN** a user runs `uvx tokenmaxxr --json`
- **THEN** the command works without a prior explicit install step

