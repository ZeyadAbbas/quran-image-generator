"""Small command-line adapter for the image generator."""

from __future__ import annotations

import argparse
import random
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quran-image-generator",
        description="Generate a customizable image from a Quran passage.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""usage modes:
  No selector: repeat with interactive chapter and verse prompts.
  --chapter/--start/--end or --random: generate once without prompts.
  One-shot mode defaults to --no-open; pass --open to show the result.

examples:
  quran-image-generator
  quran-image-generator --chapter 2 --start 255 --end 257
  quran-image-generator --random --open
  quran-image-generator --chapter 1 --start 1 --end 1 --publish story""",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        metavar="PATH",
        help="YAML settings file (default: config.yaml in the current directory)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        metavar="PATH",
        help="override the configured output directory",
    )
    parser.add_argument("--chapter", type=int, metavar="N", help="chapter number")
    parser.add_argument(
        "--start", type=int, metavar="N", help="first verse number (inclusive)"
    )
    parser.add_argument(
        "--end", type=int, metavar="N", help="last verse number (inclusive)"
    )
    parser.add_argument(
        "--random",
        action="store_true",
        help="generate one short, randomly selected passage",
    )
    parser.add_argument(
        "--open",
        dest="open_output",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="open the generated image (one-shot runs default to --no-open)",
    )
    parser.add_argument(
        "--publish",
        choices=("post", "story"),
        metavar="{post,story}",
        help=(
            "publish every successfully generated image in this run to Instagram; requires "
            "the optional instagram extra and QIG_INSTAGRAM_USERNAME/"
            "QIG_INSTAGRAM_PASSWORD credentials (or interactive prompts)"
        ),
    )
    return parser


def _validate_selection(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    values = (args.chapter, args.start, args.end)
    supplied = tuple(value is not None for value in values)
    if any(supplied) and not all(supplied):
        parser.error("--chapter, --start, and --end must be provided together")
    if args.random and any(supplied):
        parser.error("--random cannot be combined with --chapter/--start/--end")
    if not all(supplied):
        return
    if not 1 <= args.chapter <= 114:
        parser.error("--chapter must be between 1 and 114")
    if args.start < 1:
        parser.error("--start must be at least 1")
    if args.end < args.start:
        parser.error("--end must be greater than or equal to --start")


def _verse_bounds() -> tuple[int, ...]:
    from .resources import asset_path

    path = asset_path("verse_bounds.txt")
    bounds = tuple(
        int(line.strip())
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if len(bounds) != 114 or any(bound < 1 for bound in bounds):
        raise RuntimeError(f"Invalid packaged verse bounds: {path}")
    return bounds


def _validate_range(
    parser: argparse.ArgumentParser,
    chapter: int,
    starting_verse: int,
    ending_verse: int,
    bounds: tuple[int, ...],
) -> None:
    maximum = bounds[chapter - 1]
    if starting_verse > maximum:
        parser.error(
            f"--start must be between 1 and {maximum} for chapter {chapter}"
        )
    if ending_verse > maximum:
        parser.error(
            f"--end must be between {starting_verse} and {maximum} "
            f"for chapter {chapter}"
        )


def _prompt_for_range(bounds: tuple[int, ...]) -> tuple[int, int, int]:
    while True:
        try:
            chapter = int(input("\nInput chapter: "))
            if not 1 <= chapter <= 114:
                raise ValueError
            break
        except ValueError:
            print("Invalid input. Please input an integer value between 1 and 114.")

    maximum = bounds[chapter - 1]
    while True:
        try:
            starting_verse = int(input("Input starting verse: "))
            if not 1 <= starting_verse <= maximum:
                raise ValueError
            break
        except ValueError:
            print(
                "Invalid input. Please input an integer value between "
                f"1 and {maximum}."
            )

    while True:
        try:
            ending_verse = int(input("Input ending verse: "))
            if not starting_verse <= ending_verse <= maximum:
                raise ValueError
            break
        except ValueError:
            print(
                "Invalid input. Please input an integer value between "
                f"{starting_verse} and {maximum}."
            )

    return chapter, starting_verse, ending_verse


def _random_range(bounds: tuple[int, ...]) -> tuple[int, int, int]:
    chapter = random.randint(1, len(bounds))
    maximum = bounds[chapter - 1]
    starting_verse = random.randint(1, maximum)
    ending_verse = min(
        random.randint(starting_verse, starting_verse + random.randint(1, 4)),
        maximum,
    )
    return chapter, starting_verse, ending_verse


def _confirm(prompt: str) -> bool:
    while True:
        answer = input(prompt).strip().lower()
        if answer == "y":
            return True
        if answer == "n":
            return False


def _settings_with_output_directory(settings: Any, override: Path | None) -> Any:
    output_directory = settings.output_path
    if override is not None:
        output_directory = override.expanduser()
        if not output_directory.is_absolute():
            output_directory = Path.cwd() / output_directory
        output_directory = output_directory.resolve(strict=False)

    if output_directory.exists() and not output_directory.is_dir():
        raise ValueError(f"output directory is an existing file: {output_directory}")
    output_directory.mkdir(parents=True, exist_ok=True)
    return replace(settings, output_path=output_directory)


def _publish_generated_image(image_path: Path, target_value: str) -> None:
    from .publishing import (
        InstagramPublisher,
        PublishTarget,
        resolve_instagram_credentials,
    )

    credentials = resolve_instagram_credentials()
    publisher = InstagramPublisher(credentials)
    publisher.publish(image_path, PublishTarget(target_value))


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    from .content import QuranApiError
    from .generator import build_generator
    from .models import GenerationRequest
    from .settings import SettingsValidationError, load_settings

    one_shot = args.random or args.chapter is not None
    bounds = _verse_bounds()
    explicit_selection: tuple[int, int, int] | None = None
    if args.chapter is not None:
        explicit_selection = (args.chapter, args.start, args.end)
        _validate_range(parser, *explicit_selection, bounds)
    elif args.random:
        explicit_selection = _random_range(bounds)

    while True:
        try:
            settings = load_settings(args.config, create_output_dir=False)
            settings = _settings_with_output_directory(settings, args.output_dir)
            generator = build_generator(settings)
        except (OSError, SettingsValidationError, ValueError) as error:
            parser.exit(2, f"{error}\n")

        if explicit_selection is not None:
            selected = explicit_selection
        elif settings.generate_random_verses:
            selected = _random_range(bounds)
        else:
            selected = _prompt_for_range(bounds)

        request = GenerationRequest(*selected)
        open_output = args.open_output
        if open_output is None:
            open_output = not one_shot

        try:
            result = generator.generate(request, open_output=open_output)
        except QuranApiError as error:
            parser.exit(1, f"Quran API error: {error}\n")

        if args.publish is not None:
            from .publishing import PublishingError

            if result.path is None:
                print(
                    "Instagram publishing was requested, but generation did not "
                    "produce an image.",
                    file=sys.stderr,
                )
                return 3
            generated_path = Path(result.path)
            if not generated_path.is_file():
                print(
                    "Instagram publishing was requested, but the generated image "
                    f"could not be found at: {generated_path}",
                    file=sys.stderr,
                )
                return 3
            try:
                _publish_generated_image(generated_path, args.publish)
            except PublishingError as error:
                print(f"Instagram publishing failed: {error}", file=sys.stderr)
                print(f"Generated image retained at: {result.path}", file=sys.stderr)
                return 3
            print(f"Published generated image to Instagram {args.publish}.")

        if one_shot:
            return 0

        if not _confirm("Generate another? [y/n]: "):
            return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_selection(parser, args)
    return _run(parser, args)
