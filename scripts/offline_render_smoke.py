"""Render one fixture-backed PNG without credentials, network, or a GUI."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from wand.image import Image

from quran_image_generator.content import parse_verse
from quran_image_generator.layout import build_layout
from quran_image_generator.models import Chapter, Passage
from quran_image_generator.rendering import WandImageRenderer, WandTextMeasurer
from quran_image_generator.resources import asset_path
from quran_image_generator.settings import Dimensions, Settings

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _load_fixture(path: Path) -> Mapping[str, Any]:
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"fixture must contain a JSON object: {path}")
    return cast(dict[str, Any], payload)


def _settings(output_directory: Path, fixture: Path) -> Settings:
    return Settings(
        source_path=fixture,
        output_path=output_directory,
        resolution=Dimensions(640, 420),
        background_image=None,
        background_color="#101820",
        quran_font=asset_path("fonts", "quran_font.ttf"),
        quran_color="#FFFFFF",
        quran_font_size=44,
        quran_x_position="center",
        quran_max_width=560,
        quran_line_spacing=10,
        quran_word_spacing=4,
        quran_letter_spacing=0.0,
        quran_translation_spacing=20,
        translations=(),
        translation_color="#FFFFFF",
        translation_font_size=20,
        translation_x_position="center",
        translation_max_width=560,
        translation_language_spacing=8,
        translation_line_spacing=5,
        translation_word_spacing=2,
        translation_letter_spacing=0.0,
        show_verse_numbers=True,
        verse_number_resolution=Dimensions(40, 40),
        verse_number_x_offset=6,
        verse_number_y_offset=0,
        space_between_verses=20,
        generate_random_verses=False,
        total_y_offset=0,
    )


def render_smoke(fixture: Path, output_directory: Path) -> Path:
    """Render and validate a real PNG from a checked-in API fixture."""

    output_directory.mkdir(parents=True, exist_ok=True)
    verse = parse_verse(_load_fixture(fixture), ())
    passage = Passage(Chapter(1, "Al-Fatihah", 7), (verse,))
    settings = _settings(output_directory, fixture)
    layout = build_layout(passage, settings, WandTextMeasurer())
    destination = output_directory / "offline-smoke.png"
    WandImageRenderer().render(layout, settings, destination)

    if destination.read_bytes()[: len(PNG_SIGNATURE)] != PNG_SIGNATURE:
        raise RuntimeError(f"renderer did not create a PNG: {destination}")
    with Image(filename=str(destination)) as image:
        if image.format != "PNG" or (image.width, image.height) != (640, 420):
            raise RuntimeError(
                "rendered image has unexpected format or dimensions: "
                f"{image.format} {image.width}x{image.height}"
            )
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    rendered = render_smoke(args.fixture.resolve(), args.output_dir.resolve())
    print(f"Offline render smoke passed: {rendered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
