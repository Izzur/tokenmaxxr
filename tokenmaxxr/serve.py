"""FastAPI server: /api/usage, /api/refresh, /api/history + static WebUI.

Optional — requires the [serve] extra.
"""

from __future__ import annotations

from pathlib import Path

try:
    from fastapi import FastAPI, Query
    from fastapi.responses import FileResponse, JSONResponse
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "serve requires the [serve] extra: pip install 'tokenmaxxr[serve]'"
    ) from e

from tokenmaxxr import fetch_all
from tokenmaxxr.history import read_all


def _build_app() -> "FastAPI":
    app = FastAPI(title="tokenmaxxr", version="0.1.0")

    @app.get("/api/usage")
    def usage(provider: list[str] | None = Query(default=None)) -> dict:
        return fetch_all(providers=provider)

    @app.post("/api/refresh")
    def refresh(provider: list[str] | None = Query(default=None)) -> dict:
        return fetch_all(providers=provider, refresh=True)

    @app.get("/api/history")
    def history(
        provider: str | None = None,
        window: str | None = None,
    ) -> JSONResponse:
        return JSONResponse(read_all(provider=provider, window=window))

    # Static WebUI.
    dist = Path(__file__).parent / "_webui" / "dist"
    if dist.exists():
        @app.get("/")
        def root() -> FileResponse:
            return FileResponse(dist / "index.html")

        @app.get("/{path:path}")
        def spa(path: str) -> FileResponse:
            target = dist / path
            if target.is_file():
                return FileResponse(target)
            return FileResponse(dist / "index.html")
    else:

        @app.get("/")
        def missing_webui() -> dict:
            return {
                "error": "web/dist not built; run `cd web && npm run build` "
                "or skip the UI and use --json",
            }

    return app


def run(*, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(_build_app(), host=host, port=port)


app = _build_app()
