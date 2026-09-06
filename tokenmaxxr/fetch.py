"""Top-level fetch orchestrator: wires cookies + cache + history + providers.

Single function, `fetch_all`, used by both the CLI and the FastAPI server.
Per-provider failures never abort other providers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from tokenmaxxr import cache, config, history
from tokenmaxxr.cookies import resolve as resolve_cookies
from tokenmaxxr.providers import NoAuth, get_provider, known_slugs
from tokenmaxxr.schema import ProviderResult, build_document

log = logging.getLogger(__name__)


def fetch_all(
    *,
    providers: list[str] | None = None,
    refresh: bool = False,
    cookie_overrides: dict[str, str] | None = None,
) -> dict:
    """Collect usage for each requested provider and return the schema:1 doc."""
    cookie_overrides = cookie_overrides or {}
    slugs = providers or config.select_providers(known_slugs())
    results: list[ProviderResult] = []
    for slug in slugs:
        results.append(_collect_one(slug, refresh=refresh, override=cookie_overrides.get(slug)))
    return build_document(results, fetched_at=datetime.now(timezone.utc))


def _collect_one(
    slug: str, *, refresh: bool, override: str | None
) -> ProviderResult:
    provider = get_provider(slug)

    # Cache: serve fresh hit unless caller asked for refresh.
    if not refresh:
        cached = cache.read(slug)
        if cached is not None:
            return cached

    if refresh:
        # `--refresh` invalidates the latest-value cache but NEVER touches
        # `history.jsonl` — history is append-only and reflects every
        # successful LIVE fetch, regardless of how it was triggered.
        cache.invalidate(slug)
    # Cookie resolution (skipped for token-based providers).
    jar = None
    if provider.cookie_domain:
        jar, _source = resolve_cookies(provider.cookie_domain, override=override)
        if jar is None:
            return ProviderResult(
                id=slug,
                name=provider.name,
                status="no-auth",
                error=f"no cookies for {provider.cookie_domain}",
            )

    # Live fetch.
    try:
        raw = provider.fetch_raw(jar)
        windows = provider.to_rows(raw)
    except NoAuth as e:
        return ProviderResult(id=slug, name=provider.name, status="no-auth", error=str(e))
    except Exception as e:  # noqa: BLE001 — boundary, isolate per-provider
        log.warning("provider %s failed: %s", slug, e)
        stale = cache.read_any_age(slug)
        if stale is not None:
            return stale
        return ProviderResult(
            id=slug,
            name=provider.name,
            status="error",
            error=str(e),
        )

    result = ProviderResult(
        id=slug, name=provider.name, status="ok", windows=windows
    )
    cache.write(slug, result)
    history.append(result)
    return result
