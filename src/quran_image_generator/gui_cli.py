"""Display-safe launcher for the optional standard-library desktop GUI."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quran-image-generator-gui",
        description=(
            "Open the lightweight Quran image generator desktop interface. "
            "API credentials can be entered in the app for the current session."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="optionally load an existing YAML config after the window opens",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Importing Tk is intentionally delayed until after argparse handles --help.
    try:
        from .gui import launch
    except ImportError as error:
        if error.name in {"tkinter", "_tkinter"}:
            print(
                "The desktop GUI requires Python's optional tkinter support. "
                "Install the Tk package for this Python installation and retry.",
                file=sys.stderr,
            )
            return 2
        raise

    return launch(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
