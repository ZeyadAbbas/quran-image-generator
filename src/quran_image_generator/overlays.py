"""Strict straight-alpha PNG overlays with explicit full/cropped placement."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from wand.drawing import Drawing
from wand.image import Image

from .layout import ImageLayout
from .references import ReferenceError
from .rendering import VERSE_NUMBERS_FOLDER, _apply_style


@dataclass(frozen=True, slots=True)
class OverlayAsset:
    sha256: str
    width: int
    height: int
    offset: tuple[int, int]
    bounds: tuple[int, int, int, int] | None
    alpha_mode: str = "straight"
    color_space: str = "sRGB"


def alpha_bounds(image: Image) -> tuple[int, int, int, int] | None:
    raw = image.export_pixels(channel_map="A", storage="char")
    left, top, right, bottom = image.width, image.height, -1, -1
    for i, alpha in enumerate(raw):
        if alpha:
            x, y = i % image.width, i // image.width
            left, top, right, bottom = min(left, x), min(top, y), max(right, x), max(bottom, y)
    if right < 0:
        return None
    return left, top, right + 1, bottom + 1


def save_overlay(image: Image, destination: Path, *, cropped: bool = False) -> OverlayAsset:
    """Save PNG with straight alpha; boxes use full-canvas half-open pixels."""
    bounds = alpha_bounds(image)
    offset = (0, 0)
    with image.clone() as output:
        output.colorspace = "srgb"
        output.alpha_channel = "activate"
        output.format = "png"
        output.options["png:color-type"] = "6"
        if cropped and bounds is not None:
            left, top, right, bottom = bounds
            output.crop(left=left, top=top, width=right-left, height=bottom-top, reset_coords=True)
            offset = (left, top)
        output.save(filename=str(destination))
        return OverlayAsset(hashlib.sha256(destination.read_bytes()).hexdigest(), output.width, output.height, offset, bounds)


def render_overlay(layout: ImageLayout, destination: Path, *, opacity: float = 1,
                   cropped: bool = False, marker_directory: Path = VERSE_NUMBERS_FOLDER) -> OverlayAsset:
    if not 0 <= opacity <= 1:
        raise ReferenceError("invalid_request", "Layer opacity must be in 0..1")
    with Image(width=layout.width, height=layout.height, background="transparent") as image:
        for marker in layout.markers:
            path = marker_directory / f"{marker.number}.png"
            if not path.is_file():
                raise ReferenceError("missing_asset", f"Required verse marker {marker.number} is missing")
            with Image(filename=str(path)) as artwork:
                artwork.resize(marker.width, marker.height)
                image.composite(artwork, int(marker.x), int(marker.y))
        with Drawing() as draw:
            for line in layout.lines:
                _apply_style(draw, line.style)
                draw.text(int(line.x), int(line.y), line.text)
            draw(image)
        if opacity != 1:
            image.evaluate(operator="multiply", value=opacity, channel="alpha")
        return save_overlay(image, destination, cropped=cropped)
