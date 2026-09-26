"""Stable filesystem paths for resources installed with the package."""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIRECTORY = Path(__file__).resolve().parent
ASSETS_DIRECTORY = PACKAGE_DIRECTORY / "assets"


def asset_path(*parts: str) -> Path:
    """Return an absolute path inside the package's asset directory."""

    return ASSETS_DIRECTORY.joinpath(*parts)
