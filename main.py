"""Compatibility launcher for source checkouts."""

from __future__ import annotations

import sys
from pathlib import Path


def _run() -> int:
    source_directory = Path(__file__).resolve().parent / "src"
    if source_directory.is_dir():
        sys.path.insert(0, str(source_directory))

    from quran_image_generator.cli import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
