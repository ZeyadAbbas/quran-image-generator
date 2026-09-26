"""Small command-line adapter for the image generator."""

from __future__ import annotations

import argparse
import random
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import (
    Chapter,
    GenerationRequest,
    InvalidVerseRangeError,
    random_generation_request,
    validate_generation_request,
)


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
  quran-image-generator --list-translations
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
    parser.add_argument(
        "--list-translations",
        action="store_true",
        help=(
            "list live Quran Foundation translation IDs, slugs, languages, "
            "names, and authors, then exit"
        ),
    )
    parser.add_argument(
        "--refresh-catalog",
        action="store_true",
        help="force a fresh catalog request with --list-translations",
    )
    return parser


def _validate_selection(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    values = (args.chapter, args.start, args.end)
    supplied = tuple(value is not None for value in values)
    if args.refresh_catalog and not args.list_translations:
        parser.error("--refresh-catalog requires --list-translations")
    if args.list_translations and (
        any(supplied)
        or args.random
        or args.open_output is not None
        or args.publish is not None
        or args.output_dir is not None
    ):
        parser.error(
            "--list-translations cannot be combined with generation or publishing options"
        )
    if any(supplied) and not all(supplied):
        parser.error("--chapter, --start, and --end must be provided together")
    if args.random and any(supplied):
        parser.error("--random cannot be combined with --chapter/--start/--end")
    if not all(supplied):
        return
    try:
        GenerationRequest(args.chapter, args.start, args.end)
    except InvalidVerseRangeError as error:
        parser.error(str(error))


def _prompt_for_range(chapters: tuple[Chapter, ...]) -> GenerationRequest:
    chapters_by_number = {chapter.number: chapter for chapter in chapters}
    available = ", ".join(str(number) for number in chapters_by_number)
    while True:
        try:
            chapter = int(input("\nInput chapter: "))
            if chapter not in chapters_by_number:
                raise ValueError
            break
        except ValueError:
            print(f"Invalid input. Available chapter numbers: {available}.")

    maximum = chapters_by_number[chapter].verses_count
    while True:
        try:
            starting_verse = int(input("Input starting verse: "))
            if not 1 <= starting_verse <= maximum:
                raise ValueError
            break
        except ValueError:
            print(
                f"Invalid input. Please input an integer value between 1 and {maximum}."
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

    return GenerationRequest(chapter, starting_verse, ending_verse)


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


def _list_translations(parser: argparse.ArgumentParser, *, refresh: bool) -> int:
    from .content import (
        QuranApiConfigurationError,
        QuranApiError,
        QuranContentClient,
    )

    try:
        catalog = QuranContentClient.from_environment().translation_catalog(
            refresh=refresh
        )
    except QuranApiConfigurationError as error:
        parser.exit(2, f"{error}\n")
    except QuranApiError as error:
        parser.exit(1, f"Quran API error: {error}\n")

    print("ID | Slug | Language | Translation | Author")
    for resource in sorted(
        catalog.resources,
        key=lambda item: (
            item.language_name.casefold(),
            item.name.casefold(),
            int(item.resource_id),
        ),
    ):
        language = resource.language_code or resource.language_name
        print(
            f"{resource.resource_id} | {resource.slug or '-'} | {language} | "
            f"{resource.name} | {resource.author_name}"
        )
    return 0


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    from .content import (
        QuranApiConfigurationError,
        QuranApiError,
        QuranContentClient,
    )
    from .generator import build_generator
    from .settings import SettingsValidationError, load_settings

    if args.list_translations:
        return _list_translations(parser, refresh=args.refresh_catalog)

    one_shot = args.random or args.chapter is not None
    try:
        content_client = QuranContentClient.from_environment()
        chapters = content_client.list_chapters()
    except QuranApiConfigurationError as error:
        parser.exit(2, f"{error}\n")
    except QuranApiError as error:
        parser.exit(1, f"Quran API error: {error}\n")

    rng = random.Random()
    explicit_request: GenerationRequest | None = None
    if args.chapter is not None:
        try:
            explicit_request = GenerationRequest(args.chapter, args.start, args.end)
            validate_generation_request(explicit_request, chapters)
        except InvalidVerseRangeError as error:
            parser.exit(2, f"{error}\n")
    elif args.random:
        explicit_request = random_generation_request(chapters, rng)

    while True:
        try:
            settings = load_settings(args.config, create_output_dir=False)
            settings = _settings_with_output_directory(settings, args.output_dir)
            generator = build_generator(settings, content_client=content_client)
        except (OSError, SettingsValidationError, ValueError) as error:
            parser.exit(2, f"{error}\n")

        if explicit_request is not None:
            request = explicit_request
        elif settings.generate_random_verses:
            request = random_generation_request(chapters, rng)
        else:
            request = _prompt_for_range(chapters)

        open_output = args.open_output
        if open_output is None:
            open_output = not one_shot

        try:
            result = generator.generate(request, open_output=open_output)
        except InvalidVerseRangeError as error:
            if one_shot:
                parser.exit(2, f"{error}\n")
            print(f"Invalid passage: {error}", file=sys.stderr)
            continue
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
