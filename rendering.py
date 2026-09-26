"""Wand/ImageMagick adapters for measuring and rendering image layouts."""

from __future__ import annotations

from pathlib import Path

from wand.drawing import Drawing
from wand.image import Image

from layout import ImageLayout, TextMetrics, TextStyle
from settings import Settings

VERSE_NUMBERS_FOLDER = Path("assets/verse_numbers")


def _apply_style(draw: Drawing, style: TextStyle) -> None:
    draw.font = str(style.font)
    draw.font_size = style.font_size
    draw.fill_color = style.color
    draw.text_kerning = style.letter_spacing
    draw.max_width = style.max_width
    draw.word_spacing = style.word_spacing


class WandTextMeasurer:
    def measure(self, text: str, style: TextStyle) -> TextMetrics:
        with Image(width=1, height=1) as image, Drawing() as draw:
            _apply_style(draw, style)
            metrics = draw.get_font_metrics(image, text)
        return TextMetrics(
            width=metrics.text_width,
            height=metrics.text_height,
            ascender=max(0.0, metrics.ascender),
            descender=max(0.0, -metrics.descender),
        )


class WandImageRenderer:
    def __init__(self, verse_numbers_folder: Path = VERSE_NUMBERS_FOLDER) -> None:
        self._verse_numbers_folder = verse_numbers_folder

    def render(
        self,
        layout: ImageLayout,
        settings: Settings,
        destination: Path,
    ) -> Path:
        with Image(
            width=layout.width,
            height=layout.height,
            pseudo=f"xc:{settings.background_color}",
        ) as image:
            if settings.background_image is not None:
                with Image(filename=str(settings.background_image)) as background:
                    image.composite(background, 0, 0)

            for marker in layout.markers:
                marker_path = self._verse_numbers_folder / f"{marker.number}.png"
                try:
                    with Image(filename=str(marker_path)) as marker_image:
                        marker_image.resize(marker.width, marker.height)
                        image.composite(marker_image, int(marker.x), int(marker.y))
                # The legacy renderer treats every marker failure as non-fatal.
                except Exception as error:  # noqa: BLE001
                    print(f"Error loading {marker_path}: {error}")

            with Drawing() as draw:
                for line in layout.lines:
                    _apply_style(draw, line.style)
                    draw.text(int(line.x), int(line.y), line.text)
                draw(image)

            image.save(filename=str(destination))

        return destination
