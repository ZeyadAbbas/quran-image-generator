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
            "Bundled Arabic content works offline; optional translations use QuranEnc."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="optionally load an existing YAML config after the window opens",
    )
    parser.add_argument(
        "--captions",
        action="store_true",
        help="open the general caption, layer and phrase translation editor",
    )
    parser.add_argument(
        "--request",
        type=Path,
        help="open a saved caption JSON request in Caption Studio",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.config and (args.captions or args.request):
        parser.error(
            "--config is for still-image YAML; use --request for Caption Studio"
        )
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

    if args.captions or args.request:
        return launch(captions=True, request_path=args.request)
    return launch(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
