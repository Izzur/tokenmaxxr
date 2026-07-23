"""tokenmaxxr — aggregate AI subscription quota usage into one view."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("tokenmaxxr")
except PackageNotFoundError:  # running from raw checkout, not installed
    __version__ = "0.0.0+unknown"

from tokenmaxxr.schema import ProviderResult, UsageWindow, build_document, status_of
from tokenmaxxr.fetch import fetch_all

__all__ = [
    "ProviderResult",
    "UsageWindow",
    "build_document",
    "fetch_all",
    "status_of",
    "__version__",
]
