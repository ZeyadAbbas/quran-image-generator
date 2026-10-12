"""Complete-line RAQM text with cached fonts and spacing-aware font advances."""

from __future__ import annotations

import hashlib
import os
import threading
import unicodedata
from io import BytesIO
from pathlib import Path

from PIL import ImageFont

from .backends import require_pillow_shaping
from .render_cache import RenderCache, file_identity
from .resources import asset_path

_font_cache: RenderCache[tuple, ImageFont.FreeTypeFont] = RenderCache(64)
_source_cache: RenderCache[tuple, bytes] = RenderCache(32, max_bytes=32 * 1024 * 1024)
_spaced_cache: RenderCache[tuple, bytes] = RenderCache(64, max_bytes=32 * 1024 * 1024)
_units_cache: RenderCache[tuple, int] = RenderCache(32)


def text_direction(text: str) -> str:
    for char in text:
        direction = unicodedata.bidirectional(char)
        if direction in ("R", "AL"):
            return "rtl"
        if direction == "L":
            return "ltr"
    return "ltr"


def font_path(path: str | Path, *, direction: str) -> str:
    if str(path).lower() != "arial":
        return str(path)
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf"
    if windows.is_file():
        return str(windows)
    return str(
        asset_path("fonts", "quran_font.ttf")
        if direction == "rtl"
        else asset_path("fonts", "multilingual_fonts", "am.ttf")
    )


def shaped_font(
    path: str | Path,
    size: int | float,
    *,
    direction: str = "rtl",
    letter_spacing: float = 0,
    word_spacing: float = 0,
    sha256: str = "",
) -> ImageFont.FreeTypeFont:
    """Keep bidi/Arabic joins intact while changing advancing glyph/space widths.

    Pillow has no arbitrary letter/word-spacing parameter. Adjust hmtx advances
    in an in-memory font, leaving outlines, cmap, joining and mark anchors intact.
    Zero-advance marks remain zero. The source font and its pinned hash never change.
    """
    require_pillow_shaping()
    resolved = font_path(path, direction=direction)
    identity = file_identity(resolved)
    source_key = (sha256,) if sha256 else identity
    key = threading.get_ident(), source_key, size, letter_spacing, word_spacing
    cached = _font_cache.get(key)
    if cached is not None:
        return cached
    data = _source_cache.get(source_key)
    if data is None:
        data = Path(resolved).read_bytes()
        if sha256 and hashlib.sha256(data).hexdigest() != sha256:
            from .references import ReferenceError

            raise ReferenceError("changed_asset", "Font changed after verification")
        _source_cache.put(source_key, data, size=len(data))
    if letter_spacing or word_spacing:
        from fontTools.ttLib import TTFont

        units = _units_cache.get(source_key)
        if units is None:
            with TTFont(BytesIO(data), lazy=True) as face:
                units = face["head"].unitsPerEm
            _units_cache.put(source_key, units)
        letter_units = round(letter_spacing * units / size)
        space_units = round(word_spacing * units / size)
        spaced_key = source_key, letter_units, space_units
        spaced = _spaced_cache.get(spaced_key)
        if spaced is None:
            spaced = _spaced_bytes(data, letter_units, space_units, letter_spacing)
            _spaced_cache.put(spaced_key, spaced, size=len(spaced))
        data = spaced
    # Load from memory: cached fonts cannot lock caller files or job-local faces.
    font = ImageFont.truetype(BytesIO(data), size, layout_engine=ImageFont.Layout.RAQM)
    _font_cache.put(key, font, size=len(data))
    return font


def _spaced_bytes(
    data: bytes, letter_units: int, space_units: int, letter_spacing: float
) -> bytes:
    from fontTools.ttLib import TTFont

    with TTFont(BytesIO(data)) as face:
        spaces = {
            glyph
            for point, glyph in (face.getBestCmap() or {}).items()
            if 0 <= point <= 0x10FFFF and chr(point).isspace()
        }
        advances = face["hmtx"].metrics
        for glyph, (advance, bearing) in advances.items():
            if advance:
                adjusted = (
                    advance + letter_units + (space_units if glyph in spaces else 0)
                )
                if not 0 < adjusted <= 65535:
                    from .references import ReferenceError

                    raise ReferenceError(
                        "unsupported_shaping_option",
                        "Spacing produces an invalid font advance",
                        details={
                            "field": "letter_spacing"
                            if letter_spacing
                            else "word_spacing"
                        },
                    )
                advances[glyph] = adjusted, bearing
        face.recalcTimestamp = False
        buffer = BytesIO()
        face.save(buffer)
        return buffer.getvalue()
