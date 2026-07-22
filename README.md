# tokenmaxxr

Aggregate AI subscription quota usage (OpenCode Go, ClinePass, Ollama Cloud) into one view.

Three providers, one engine, one versioned JSON contract. CLI for bars/dashboards, optional WebUI, optional HTTP API.

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
tokenmaxxr doctor       # diagnose cookie discovery
tokenmaxxr serve        # WebUI + HTTP API
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
        {"label": "5h", "pct_used": 47, "reset_at": "2026-07-22T20:00:00Z"}
      ]
    }
  ]
}
```

`status` is one of `ok` | `stale` | `no-auth` | `error`.

## Cookie sources

1. `--cookie-file SLUG=/path/to/cookies.sqlite` or `TOKENMAXXR_COOKIE_<DOMAIN>` env
2. Firefox-family stores (globbed: `~/.mozilla/firefox/*`, `~/.zen/*`, Zen/Firefox Flatpak paths, Floorp/LibreWolf/Waterfox)
3. Chromium-family via `browser_cookie3` (best-effort, locked keyring → skip)
4. No match → `no-auth` status + remediation in `doctor`

Cookies are copied to a temp file before reading (WAL lock-safe). Cache and history live under `~/.local/state/tokenmaxxr/`.

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
```

## License

MIT
