"""Wand/ImageMagick adapters for measuring and rendering image layouts."""

from __future__ import annotations

import ctypes
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from math import ceil
from pathlib import Path
from typing import Any

from PIL import Image as PillowImage
from wand.drawing import Drawing
from wand.image import Image

from .layout import ImageLayout, TextMetrics, TextStyle
from .render_cache import RenderCache, file_identity
from .resources import asset_path
from .settings import Settings

VERSE_NUMBERS_FOLDER = asset_path("verse_numbers")

_metrics: RenderCache[tuple, TextMetrics] = RenderCache(
    8192, max_bytes=16 * 1024 * 1024
)
_ink: RenderCache[tuple, TextMetrics] = RenderCache(8192, max_bytes=16 * 1024 * 1024)


def metric_key(text: str, style: TextStyle) -> tuple:
    identity: object = style.font_sha256
    if not identity:
        try:
            identity = file_identity(style.font)
        except OSError:
            identity = str(style.font)
    geometry = replace(
        style, color="", max_width=0, font=style.font_sha256 or style.font
    )
    return text, geometry, identity


def export_pixels(image: Any, channels: str, storage: str = "char") -> bytes:
    """Export a contiguous native buffer without creating a Python pixel list."""
    from wand.api import library
    from wand.image import STORAGE_TYPES

    element = ctypes.c_float if storage == "float" else ctypes.c_ubyte
    buffer = (element * (image.width * image.height * len(channels)))()
    if not library.MagickExportImagePixels(
        image.wand,
        0,
        0,
        image.width,
        image.height,
        channels.encode("ascii"),
        STORAGE_TYPES.index(storage),
        ctypes.byref(buffer),
    ):
        image.raise_exception()
        raise RuntimeError("Native pixel transfer failed")
    return bytes(buffer)


def wand_rgba_image(image: Any) -> PillowImage.Image:
    if image.depth <= 8:
        return PillowImage.frombytes("RGBA", image.size, export_pixels(image, "RGBA"))
    # Keep the original decoder's precision conversion for unusual 16-bit inputs.
    from io import BytesIO

    with PillowImage.open(BytesIO(image.make_blob("png"))) as encoded:
        result: PillowImage.Image = encoded.convert("RGBA")
        return result


def _apply_style(draw: Drawing, style: TextStyle) -> None:
    draw.font = str(style.font)
    draw.font_size = style.font_size
    draw.fill_color = style.color
    draw.text_kerning = style.letter_spacing
    draw.max_width = style.max_width
    draw.word_spacing = style.word_spacing
    if style.direction != "undefined":
        draw.text_direction = style.direction
    if style.additional_word_spacing:
        natural_space = style.native_space_advance
        if natural_space is None:
            with Image(width=1, height=1) as probe:
                natural_space = draw.get_font_metrics(probe, " ").text_width
        draw.text_interword_spacing = natural_space + style.additional_word_spacing


class WandTextMeasurer:
    def __init__(self) -> None:
        self._metric_cache = _metrics
        self._ink_cache = _ink

    def measure(self, text: str, style: TextStyle) -> TextMetrics:
        key = metric_key(text, style)
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
        self._metric_cache.put(key, measured, size=len(text) * 4 + 256)
        return measured

    def measure_ink(self, text: str, style: TextStyle) -> TextMetrics:
        """Measure finalized-line ink around the renderer's draw baseline."""

        key = metric_key(text, style)
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
                with PillowImage.frombytes(
                    "F", image.size, export_pixels(image, "R", "float")
                ) as mask:
                    bounds = mask.getbbox()
                if bounds is None:
                    padding *= 2
                    continue
                left, top, right, bottom = bounds

            if left > 0 and top > 0 and right < canvas_width and bottom < canvas_height:
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
                self._ink_cache.put(key, result, size=len(text) * 4 + 256)
                return result
            padding *= 2

        raise RuntimeError(f"Unable to measure rendered ink bounds for {text!r}")


class WandImageRenderer:
    def __init__(self, verse_numbers_folder: Path = VERSE_NUMBERS_FOLDER) -> None:
        self._verse_numbers_folder = verse_numbers_folder
        self._images: RenderCache[tuple, Any] = RenderCache(
            128, dispose=lambda image: image.close()
        )

    @contextmanager
    def _image(self, path: Path, size: tuple[int, int] | None = None) -> Iterator[Any]:
        key: tuple
        try:
            key = file_identity(path), size
        except OSError:
            key = (str(path), "missing"), size
        cached = self._images.copy(key, lambda image: image.clone())
        if cached is not None:
            with cached as image:
                yield image
            return
        with Image(filename=str(path)) as image:
            if size:
                image.resize(*size)
            cost = image.width * image.height * 32 if hasattr(image, "width") else 1
            if hasattr(image, "clone") and cost <= self._images.max_bytes:
                self._images.put(key, image.clone(), size=cost)
            yield image

    def close(self) -> None:
        self._images.clear()

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
                with self._image(settings.background_image) as background:
                    image.composite(background, 0, 0)

            for marker in layout.markers:
                marker_path = self._verse_numbers_folder / f"{marker.number}.png"
                try:
                    with self._image(
                        marker_path, (marker.width, marker.height)
                    ) as marker_image:
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
