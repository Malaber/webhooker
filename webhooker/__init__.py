"""webhooker package."""

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    __version__ = version("webhooker")
except PackageNotFoundError:  # pragma: no cover - fallback for non-installed source usage
    __version__ = "0.0.0"
