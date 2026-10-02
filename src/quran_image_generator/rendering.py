"""Wand/ImageMagick adapters for measuring and rendering image layouts."""

from __future__ import annotations

from math import ceil
from pathlib import Path

from wand.drawing import Drawing
from wand.image import Image

from .layout import ImageLayout, TextMetrics, TextStyle
from .resources import asset_path
from .settings import Settings

VERSE_NUMBERS_FOLDER = asset_path("verse_numbers")


def _apply_style(draw: Drawing, style: TextStyle) -> None:
    draw.font = str(style.font)
    draw.font_size = style.font_size
    draw.fill_color = style.color
    draw.text_kerning = style.letter_spacing
    draw.max_width = style.max_width
    draw.word_spacing = style.word_spacing
    if style.direction != "undefined":
        draw.text_direction = style.direction


class WandTextMeasurer:
    def __init__(self) -> None:
        self._metric_cache: dict[tuple[str, TextStyle], TextMetrics] = {}
        self._ink_cache: dict[tuple[str, TextStyle], TextMetrics] = {}

    def measure(self, text: str, style: TextStyle) -> TextMetrics:
        key = (text, style)
        cached = self._metric_cache.get(key)
        if cached is not None:
            return cached

        with Image(width=1, height=1) as image, Drawing() as draw:
            _apply_style(draw, style)
            metrics = draw.get_font_metrics(image, text)
        measured = TextMetrics(
            width=metrics.text_width,
            height=metrics.text_height,
            ascender=max(0.0, metrics.ascender),
            descender=max(0.0, -metrics.descender),
        )
        self._metric_cache[key] = measured
        return measured

    def measure_ink(self, text: str, style: TextStyle) -> TextMetrics:
        """Measure finalized-line ink around the renderer's draw baseline."""

        key = (text, style)
        cached = self._ink_cache.get(key)
        if cached is not None:
            return cached

        measured = self.measure(text, style)
        base_extent = max(
            measured.height,
            measured.ascender,
            measured.descender,
            style.font_size,
            1,
        )
        padding = ceil(base_extent) + 2

        for _attempt in range(4):
            baseline = padding * 2
            canvas_width = max(1, ceil(measured.width) + padding * 2 + 1)
            canvas_height = padding * 4 + 1
            with (
                Image(
                    width=canvas_width,
                    height=canvas_height,
                    pseudo="xc:#000000",
                ) as image,
                Drawing() as draw,
            ):
                _apply_style(draw, style)
                draw.fill_color = "#FFFFFF"
                draw.text(padding, baseline, text)
                draw(image)
                with image.clone() as trimmed:
                    trimmed.trim()
                    left = trimmed.page_x
                    top = trimmed.page_y
                    right = left + trimmed.width
                    bottom = top + trimmed.height

            if (
                left > 0
                and top > 0
                and right < canvas_width
                and bottom < canvas_height
            ):
                result = TextMetrics(
                    width=measured.width,
                    height=measured.height,
                    ascender=measured.ascender,
                    descender=measured.descender,
                    top_extent=max(0, baseline - top),
                    bottom_extent=max(0, bottom - baseline),
                    left_offset=left - padding,
                    right_offset=right - padding,
                )
                self._ink_cache[key] = result
                return result
            padding *= 2

        raise RuntimeError(f"Unable to measure rendered ink bounds for {text!r}")


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
