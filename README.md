# tokenmaxxr

Aggregate AI subscription quota usage (Claude, AWS Kiro, ClinePass, Command Code, Nous Portal, Ollama Cloud, OpenCode Go) into one view.

Seven providers, one engine, one versioned JSON contract. CLI for bars/dashboards, a DankMaterialShell bar plugin, optional WebUI, optional HTTP API.

## Install

```bash
# from PyPI (recommended)
uvx tokenmaxxr --json

# from source
git clone https://github.com/Izzur/tokenmaxxr
cd tokenmaxxr
uv pip install -e ".[serve]"  # add [serve] for `tokenmaxxr serve`
```

## Quickstart

```bash
tokenmaxxr              # human table
tokenmaxxr --json       # machine-readable schema:1
tokenmaxxr --refresh    # bypass the 300s cache
tokenmaxxr doctor       # live-check auth + fetch per provider (exit 1 on failure)
tokenmaxxr serve        # WebUI + HTTP API
tokenmaxxr login nous-portal   # one-time Nous Portal login (see Auth sources)
```

## Web UI

`tokenmaxxr serve` (requires `pip install 'tokenmaxxr[serve]'`) starts a small FastAPI app on `127.0.0.1:8765`:

- `GET  /api/usage`   — schema:1 document (same as `tokenmaxxr --json`)
- `POST /api/refresh` — force a live re-fetch
- `GET  /api/history?provider=&window=` — appended history rows
- `GET  /`           — vanilla-JS dashboard (cards + history chart, opt-in 60s auto-refresh)

The dashboard degrades gracefully: with no cookies, every card shows `no-auth` and a hint.

## Output contract

`tokenmaxxr --json` returns a stable, versioned document:

```json
{
  "schema": 1,
  "fetched_at": "2026-07-22T12:00:00Z",
  "providers": [
    {
      "id": "ollama-cloud",
      "name": "Ollama Cloud",
      "status": "ok",
      "windows": [
        {"label": "30d", "pct_used": 46, "reset_at": "2026-07-22T20:00:00Z",
         "used": 27.5, "limit": 60, "unit": "$"}
      ]
    }
  ]
}
```

`status` is one of `ok` | `stale` | `no-auth` | `error`. `used` / `limit` /
`unit` appear only when the provider reports absolute amounts (`unit` is `$`
or a plural noun like `credits`).

## Config

`$XDG_CONFIG_HOME/tokenmaxxr/config.toml` (default `~/.config/tokenmaxxr/config.toml`), optional:

```toml
include = ["claude", "kiro"]   # whitelist: only these providers
exclude = ["opencode-go"]      # blacklist: everything except these
```

`include` is applied first, then `exclude`. `--provider` on the CLI overrides both.

## Auth sources

Two kinds of provider:

| Provider | Slug | Auth |
|---|---|---|
| Claude | `claude` | Claude Code OAuth token, `$CLAUDE_CONFIG_DIR/.credentials.json` (default `~/.claude/`). Log in once with `claude`. |
| AWS Kiro | `kiro` | kiro-cli token in `~/.local/share/kiro-cli/data.sqlite3`, else Kiro IDE `~/.aws/sso/cache/kiro-auth-token.json`. Log in with `kiro-cli login`. |
| ClinePass | `clinepass` | browser cookies for `app.cline.bot` + `api.cline.bot` |
| Command Code | `commandcode` | browser cookies for `commandcode.ai` (session cookie, sent to `api.commandcode.ai`) |
| Nous Portal | `nous-portal` | Run `tokenmaxxr login nous-portal` once: it prints a link, you approve it in the browser, and tokenmaxxr keeps its own OAuth token in `~/.local/state/tokenmaxxr/nous-portal-auth.json`. The portal only accepts Hermes Agent's OAuth client, so the approval page calls it Hermes. Without a login (or after deleting that file) it falls back to browser cookies for `portal.nousresearch.com`, which last only about an hour after the portal was last open. API keys can't read the balance. |
| Ollama Cloud | `ollama-cloud` | browser cookies for `ollama.com` |
| OpenCode Go | `opencode-go` | browser cookies for `opencode.ai` |

Token providers never refresh tokens themselves (that could invalidate the
CLI's own session). Kiro tokens expire hourly, so an expired one makes
tokenmaxxr run `kiro-cli whoami`, which refreshes in place. An expired Claude
token shows as `no-auth`; run `claude` once and the next poll succeeds.
The Nous Portal login is the exception: no other app holds that token, so
tokenmaxxr refreshes it itself. Nous refresh tokens work only once, so
refreshes run under a file lock.

## Cookie sources

1. `--cookie-file SLUG=/path/to/cookies.sqlite` or `TOKENMAXXR_COOKIE_<DOMAIN>` env
2. Firefox-family stores (globbed: `~/.mozilla/firefox/*`, `~/.zen/*`, Zen/Firefox Flatpak paths, Floorp/LibreWolf/Waterfox)
3. Chromium-family via `browser_cookie3` (best-effort, locked keyring → skip)
4. No match → `no-auth` status + remediation in `doctor`

Cookies are copied to a temp file before reading (WAL lock-safe). Cache and history live under `~/.local/state/tokenmaxxr/`.

## DankMaterialShell (Dankbar)

```bash
uv tool install tokenmaxxr                       # puts `tokenmaxxr` on ~/.local/bin
git clone https://github.com/Izzur/tokenmaxxr
ln -s "$PWD/tokenmaxxr/dms/TokenMaxxr" ~/.config/DankMaterialShell/plugins/TokenMaxxr
```

Then DMS Settings → Plugins → enable **tokenmaxxr**, and add it to a bar
section. Left click opens a popout with every window, progress bar, reset
countdown and amounts (`$0.07 / $60`). Right click forces `--refresh`.

Pill modes (`pill` setting):

- `soonest` (default), e.g. `C 3d 4h`: for each provider take its longest
  window (30d, 7d, …), show the one that resets soonest and its countdown.
- `hottest`, e.g. `C 47%`: the most-used window across all providers.
- `cycle`: rotates `<tag> <pct>%` through providers every `cycleSeconds`.

The icon turns warning/error color once any window reaches `warn` / `crit`,
and `notify-send` fires once per window each time it crosses a threshold
(again after the window resets).

Pace: each popout bar has a tick at the share of the window already past
(from the label length and the reset time). A window is "over pace" when its
used % is more than 10 points past that tick, so it will run out before the
reset at this rate. Over-pace windows show "over pace" and turn warning color,
and so does the icon, even below `warn`. Windows without a length in the
label (e.g. `weekly`) or without a reset time get no tick.

Optional settings in `~/.config/DankMaterialShell/plugin_settings.json`
(DMS reads this file at startup; run `dms restart` after editing):

```json
"tokenMaxxr": {
  "enabled": true,
  "command": "tokenmaxxr --json",
  "interval": 300,
  "pill": "soonest",
  "cycleSeconds": 5,
  "warn": 70,
  "crit": 90,
  "notify": true
}
```

## Waybar

```json
"custom/tokenmaxxr": {
  "exec": "tokenmaxxr --json --provider ollama-cloud",
  "return-type": "json",
  "format": "Ollama 5h: {}%",
  "exec-on-event": true,
  "interval": 600
}
```

`--json` is the stable schema:1 contract — `jq '.providers[0].windows[0].pct_used'` always returns an integer.

## fastfetch

```text
"tokenmaxxr": {
  "type": "command",
  "key": "TKN",
  "command": "tokenmaxxr --json | jq -r '.providers[] | select(.status==\"ok\") | \"\\(.id): \\(.windows[0].pct_used)%\"' | paste -sd, -"
}
```

## Headless / `--cookie-file`

```bash
tokenmaxxr --cookie-file ollama-cloud=/srv/cookies/ollama.sqlite --json
# or
TOKENMAXXR_COOKIE_OLLAMA_COM=/srv/cookies/ollama.sqlite tokenmaxxr --json

## Development

```bash
uv sync --extra dev           # set up dev deps (pytest, fastapi, etc.)
uv run python3 -m pytest      # 32 tests, <1s
uv run python3 -m pytest tests/test_providers.py -v   # one file
```

Provider parser tests live in `tests/test_providers.py` against HTML/JSON
fixtures under `tests/fixtures/`. To add a fixture, drop a real captured
payload into `tests/fixtures/<slug>.<ext>` and write a `test_<slug>` that
feeds it through `RawHtml` and asserts on the parsed `UsageWindow`s.

## License

MIT
