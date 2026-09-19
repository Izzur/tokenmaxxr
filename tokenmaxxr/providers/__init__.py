"""Provider plugins: fetch + parse usage from a dashboard into UsageWindows."""

from tokenmaxxr.providers.base import (
    NoAuth,
    Provider,
    RawHtml,
    get_provider,
    known_slugs,
    register,
)

__all__ = ["NoAuth", "Provider", "RawHtml", "register", "get_provider", "known_slugs"]


def _import_all() -> None:
    # Importing the modules registers their providers via @register.
    from tokenmaxxr.providers import opencode_go  # noqa: F401
    from tokenmaxxr.providers import clinepass  # noqa: F401
    from tokenmaxxr.providers import ollama_cloud  # noqa: F401
    from tokenmaxxr.providers import claude  # noqa: F401
    from tokenmaxxr.providers import kiro  # noqa: F401
    from tokenmaxxr.providers import commandcode  # noqa: F401


_import_all()
