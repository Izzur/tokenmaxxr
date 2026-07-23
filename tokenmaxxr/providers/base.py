"""Provider protocol and registry.

A Provider scrapes one dashboard and returns normalized UsageWindows.
It never touches cache/history — that's fetch_all's job in tokenmaxxr.fetch.
"""

from __future__ import annotations

from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Callable, Protocol

import requests

from tokenmaxxr.schema import UsageWindow

from tokenmaxxr import __version__

@dataclass
class RawHtml:
    """Carries the fetched HTML + the URL it ended up at (after redirects)."""
    url: str
    text: str
    # Optional auth probe result (e.g. 401 from the provider's API). Set by
    # providers that want to surface a clearer error than "page is empty".
    auth_status: int | None = None
    # Optional second HTTP status (e.g. the data API call's status when the
    # first call was an auth probe). Providers that hit multiple endpoints
    # can stash both.
    usage_status: int | None = None


class Provider(Protocol):
    slug: str
    name: str
    # Domain this provider's cookies belong to (used by the resolver chain).
    cookie_domain: str

    def fetch_raw(self, cookies: CookieJar) -> RawHtml: ...
    def to_rows(self, raw: RawHtml) -> list[UsageWindow]: ...


_REGISTRY: dict[str, Callable[[], Provider]] = {}


def register(slug: str, factory: Callable[[], Provider]) -> None:
    _REGISTRY[slug] = factory


def get_provider(slug: str) -> Provider:
    if slug not in _REGISTRY:
        raise KeyError(f"unknown provider: {slug!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[slug]()


def known_slugs() -> list[str]:
    return sorted(_REGISTRY)


def make_session(cookies: CookieJar, user_agent: str = f"tokenmaxxr/{__version__}") -> requests.Session:
    """Build a requests.Session that injects the resolved cookies."""
    sess = requests.Session()
    sess.cookies = cookies
    sess.headers.update({"User-Agent": user_agent, "Accept": "text/html,*/*"})
    return sess
