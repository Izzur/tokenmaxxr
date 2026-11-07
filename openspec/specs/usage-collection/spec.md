# usage-collection Specification

## Purpose
TBD - created by archiving change add-quota-aggregator. Update Purpose after archive.
## Requirements
### Requirement: Provider plugin interface

The system SHALL define a provider plugin interface that each supported service implements. A provider plugin MUST expose a stable slug (`opencode-go`, `clinepass`, `ollama-cloud`), a display name, a `fetch_raw` operation that retrieves the raw usage payload, and a `to_rows` operation that normalizes the raw payload into a list of usage windows.

Each normalized usage window MUST include: a window label (`5h`, `7d`, `30d`, or provider-equivalent), `pct_used` (integer 0–100), and `reset_at` (absolute UTC timestamp or null when unavailable).

#### Scenario: All providers normalize to the same shape
- **WHEN** any provider plugin parses its dashboard payload
- **THEN** it returns a list of usage windows each carrying label, pct_used, and reset_at, with no provider-specific fields required by consumers

#### Scenario: Relative reset text becomes absolute UTC
- **WHEN** a provider's dashboard expresses reset as relative text (e.g. "Resets in 23 hours 32 minutes")
- **THEN** the provider converts it to an absolute UTC timestamp computed at fetch time

#### Scenario: ISO reset timestamps preferred when available
- **WHEN** a provider's dashboard exposes a machine-readable reset timestamp (e.g. a `data-time` attribute)
- **THEN** the provider parses that value directly instead of scraping relative text

### Requirement: Browser-agnostic cookie resolution

The system SHALL resolve session cookies for each provider's domain via a resolution chain, in this order: (1) explicit override (`--cookie-file` or `TOKENMAXXR_COOKIE_<PROVIDER>` env var), (2) Firefox-family cookie stores discovered by glob (including `~/.mozilla/firefox/*`, `~/.zen/*`, and Flatpak paths such as `~/.var/app/app.zen_browser.zen/.zen/*`), (3) Chromium-family stores on a best-effort basis, (4) no match, which MUST result in the provider reporting `no-auth` status rather than raising.

The system MUST copy a browser's cookie database to a temporary file before reading it, and MUST NOT write to any browser data store.

#### Scenario: Explicit override wins
- **WHEN** the user passes `--cookie-file` for a provider
- **THEN** the resolver uses that cookie file and skips all browser-store discovery for that provider

#### Scenario: Zen Flatpak profile discovered
- **WHEN** the user has a Zen Flatpak profile containing cookies for a provider domain
- **THEN** the resolver finds it via glob without any user configuration

#### Scenario: Running browser does not block reads
- **WHEN** the browser is running and its cookie database is WAL-locked
- **THEN** the resolver copies the database to a temp file and reads the copy successfully

#### Scenario: No cookies anywhere
- **WHEN** no override is given and no browser store contains cookies for a provider's domain
- **THEN** that provider reports `no-auth` status and other providers are unaffected

### Requirement: Cookie handling safety

The system MUST treat cookies as read-only secrets: cookies are only transmitted to the domain that issued them, over HTTPS, and MUST NOT be written to the cache, the history log, stdout, or any diagnostic output.

#### Scenario: Secrets never leak into state files
- **WHEN** the system writes cache or history entries
- **THEN** those entries contain only usage values (percentages, timestamps, labels) and never cookie material

### Requirement: OpenCode Go provider

The system SHALL scrape `https://opencode.ai/workspace/{workspace_id}/go`, auto-discovering `workspace_id` from the `/auth` redirect, and parse usage windows from elements marked with `data-slot="usage-item"`, reading the percentage from `data-slot="usage-value"` and the reset text from `data-slot="reset-time"`.

The provider MUST recognize the Rolling (5h), Weekly, and Monthly windows and map them to labels `5h`, `7d`, `30d`.

#### Scenario: Three windows parsed
- **WHEN** the dashboard shows Rolling, Weekly, and Monthly usage
- **THEN** the provider returns three usage windows labeled 5h, 7d, and 30d with their respective percentages and reset times

#### Scenario: Workspace id discovery
- **WHEN** the provider fetches usage without a configured workspace id
- **THEN** it follows the `/auth` redirect and extracts the `wrk_`-prefixed workspace id from the Location header

### Requirement: ClinePass provider

The system SHALL scrape `https://app.cline.bot/dashboard/subscription?personal=true` and parse usage windows from elements with `role="progressbar"` whose `aria-label` ends with " usage", reading the percentage from the `aria-valuenow` attribute and the reset time from sibling "Resets in …" text.

The provider MUST recognize the 5-Hour, Weekly, and Monthly limits and map them to labels `5h`, `7d`, `30d`.

#### Scenario: Percentage from aria-valuenow
- **WHEN** the dashboard renders a progressbar with `aria-label="Weekly Limit usage"` and `aria-valuenow="84"`
- **THEN** the provider returns a 7d window with pct_used 84

#### Scenario: Approaching-limit flag does not break parsing
- **WHEN** a window card renders an "Approaching limit" badge
- **THEN** the provider still parses that window's percentage and reset time normally

### Requirement: Ollama Cloud provider

The system SHALL scrape `https://ollama.com/dashboard` with the browser cookies for `ollama.com`.

For legacy plans the provider SHALL parse usage windows from elements whose `aria-label` starts with "Session usage " or "Weekly usage ", reading the percentage from the aria-label text and the reset time from the nearest `data-time` attribute (ISO 8601) in the element's ancestors. The provider MUST map Session to label `5h` and Weekly to label `7d`.

For credits plans (Pro / Max) the provider SHALL read the `#usage-credits-breakdown` element: the remaining balance from "Monthly credits $LEFT", and the cap and reset date from "Refills to $CAP on <Month D, YYYY>". It MUST return one window labeled `30d` with `unit` `$`, `limit` = CAP, `used` = CAP − LEFT, `pct_used` = used / CAP, and `reset_at` = that date at 00:00 UTC.

The provider MUST fail with an error when the page has neither shape.

#### Scenario: Two windows parsed
- **WHEN** the page shows Session and Weekly usage
- **THEN** the provider returns two windows labeled 5h and 7d with percentages and ISO reset timestamps

#### Scenario: Credits plan parsed
- **WHEN** the dashboard shows "Monthly credits $28.43" and "Refills to $60 on November 18, 2026."
- **THEN** the provider returns one window labeled 30d with used 31.57, limit 60, unit `$`, pct_used 53 and reset_at `2026-11-18T00:00:00Z`

#### Scenario: Layout changed
- **WHEN** the page has no usage aria-labels and no credits breakdown
- **THEN** the provider fails with an error, and other providers still return their data

### Requirement: Per-provider failure isolation

The system MUST isolate provider failures: a fetch or parse error in one provider MUST NOT prevent other providers from being collected or rendered.

#### Scenario: One provider down
- **WHEN** one provider raises during fetch or parse
- **THEN** the remaining providers still return data and the failing provider reports `error` status

