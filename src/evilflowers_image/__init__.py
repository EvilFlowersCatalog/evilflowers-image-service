"""Figures of an IP-018 extraction run: crops, gates and optional captions, reported to the catalog."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("evilflowers-image-service")
except PackageNotFoundError:  # pragma: no cover - a source checkout without `uv sync`
    __version__ = "0+unknown"
