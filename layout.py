"""Pure text measurement and positioning for generated images."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from models import Passage, Verse, VerseTranslation
from settings import Settings, TranslationSettings


@dataclass(frozen=True, slots=True)
class TextStyle:
    font: Path | str
    font_size: int
    color: str
    letter_spacing: float
    max_width: int
    word_spacing: str


@dataclass(frozen=True, slots=True)
class MeasuredLine:
    text: str
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class TextBlock:
    lines: tuple[MeasuredLine, ...]
    height: float
    style: TextStyle


@dataclass(frozen=True, slots=True)
class PositionedLine:
    text: str
    x: float
    y: float
    width: float
    height: float
    style: TextStyle


@dataclass(frozen=True, slots=True)
class VerseMarker:
    number: int
    x: float
    y: float
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class ImageLayout:
    width: int
    height: int
    content_height: float
    lines: tuple[PositionedLine, ...]
    markers: tuple[VerseMarker, ...]


@dataclass(frozen=True, slots=True)
class _VerseBlock:
    number: int
    quran: TextBlock
    translations: tuple[TextBlock, ...]


def _quran_style(settings: Settings) -> TextStyle:
    return TextStyle(
        font=settings.quran_font,
        font_size=settings.quran_font_size,
        color=settings.quran_color,
        letter_spacing=settings.quran_letter_spacing,
        max_width=settings.quran_max_width,
        word_spacing=" " * settings.quran_word_spacing,
    )


def _translation_style(
    settings: Settings, translation: TranslationSettings
) -> TextStyle:
    return TextStyle(
        font=translation.font,
        font_size=translation.font_size,
        color=settings.translation_color,
        letter_spacing=settings.translation_letter_spacing,
        max_width=settings.translation_max_width,
        word_spacing=" " * settings.translation_word_spacing,
    )


def _measure_line(text: str, style: TextStyle, measurer: Any) -> MeasuredLine:
    width, height = measurer.measure(text, style)
    return MeasuredLine(text, width, height)


def _line_height(lines: tuple[MeasuredLine, ...], spacing: int) -> float:
    total = sum(line.height + spacing for line in lines)
    return total - spacing


def layout_quran_text(
    words: tuple[str, ...], settings: Settings, measurer: Any
) -> TextBlock:
    """Measure Quran words with the legacy wrapping rules."""

    style = _quran_style(settings)
    starting_x_position = (
        settings.quran_x_position
        if settings.quran_x_position != "center"
        else 0
    )
    marker_offset = (
        settings.verse_number_resolution.width + settings.verse_number_x_offset
    )
    lines: list[MeasuredLine] = []
    current_line = ""

    for index, word in enumerate(words):
        test_line = (
            current_line + style.word_spacing + word if current_line else word
        )
        test_metrics = _measure_line(test_line, style, measurer)
        if test_metrics.width < style.max_width:
            current_line = test_line
        elif (
            index >= len(words) - 1
            and test_metrics.width
            < style.max_width - starting_x_position - marker_offset
        ):
            lines.append(_measure_line(current_line, style, measurer))
            current_line = word
        else:
            lines.append(_measure_line(current_line, style, measurer))
            current_line = word

    if current_line:
        lines.append(_measure_line(current_line, style, measurer))

    measured_lines = tuple(lines)
    return TextBlock(
        lines=measured_lines,
        height=_line_height(measured_lines, settings.quran_line_spacing),
        style=style,
    )


def _translation_words(text: str) -> tuple[str, ...]:
    pattern = re.compile(r"<[^<>]*>[^<>]*<[^<>]*>")
    normalized = re.sub(pattern, "", text).replace("\xa0", " ")
    for delimiter in ("˹", "˺"):
        normalized = "".join(normalized.split(delimiter))
    return tuple(normalized.split())


def layout_translation_text(
    translation: VerseTranslation,
    settings: Settings,
    measurer: Any,
) -> TextBlock:
    """Measure a translation with the legacy normalization and wrapping rules."""

    translation_settings = next(
        item
        for item in settings.translations
        if item.resource_id == translation.resource_id
    )
    style = _translation_style(settings, translation_settings)
    lines: list[MeasuredLine] = []
    current_line = ""

    for word in _translation_words(translation.text):
        test_line = (
            current_line + style.word_spacing + word if current_line else word
        )
        test_metrics = _measure_line(test_line, style, measurer)
        if test_metrics.width < style.max_width:
            current_line = test_line
        elif len(word) > 70:
            current_line = word[:50]
            lines.append(_measure_line(current_line, style, measurer))
            current_line = word[50:]
        else:
            lines.append(_measure_line(current_line, style, measurer))
            current_line = word

    if current_line:
        lines.append(_measure_line(current_line, style, measurer))

    measured_lines = tuple(lines)
    height = _line_height(measured_lines, settings.translation_line_spacing)
    height += settings.translation_language_spacing
    return TextBlock(lines=measured_lines, height=height, style=style)


def _layout_verse(
    verse: Verse, settings: Settings, measurer: Any
) -> _VerseBlock:
    translations = tuple(
        layout_translation_text(translation, settings, measurer)
        for translation in verse.translations
    )
    return _VerseBlock(
        number=verse.number,
        quran=layout_quran_text(verse.words, settings, measurer),
        translations=translations,
    )


def build_layout(
    passage: Passage, settings: Settings, measurer: Any
) -> ImageLayout:
    """Build a complete draw plan without performing rendering or I/O."""

    width, height = settings.resolution.as_tuple()
    verse_blocks = tuple(
        _layout_verse(verse, settings, measurer) for verse in passage.verses
    )
    if not verse_blocks:
        return ImageLayout(width, height, 0, (), ())

    total_verses_height = sum(
        block.quran.height + settings.space_between_verses
        for block in verse_blocks
    )
    total_verses_height -= settings.space_between_verses

    total_translations_height = 0.0
    if settings.translations:
        total_translations_height = sum(
            translation.height + settings.quran_translation_spacing
            for block in verse_blocks
            for translation in block.translations
        )

    content_height = total_verses_height + total_translations_height
    verse_y_position = ((height - content_height) // 2) + settings.total_y_offset
    positioned_lines: list[PositionedLine] = []
    markers: list[VerseMarker] = []

    for block in verse_blocks:
        line_y_position = verse_y_position
        last_quran_x = 0.0
        last_quran_line: MeasuredLine | None = None

        for line in block.quran.lines:
            line_y_position += line.height
            if settings.quran_x_position == "center":
                x_position = (width / 2) - (line.width // 2)
            else:
                x_position = abs(
                    width - line.width - settings.quran_x_position
                )
            positioned_lines.append(
                PositionedLine(
                    line.text,
                    x_position,
                    line_y_position,
                    line.width,
                    line.height,
                    block.quran.style,
                )
            )
            last_quran_x = x_position
            last_quran_line = line
            line_y_position += settings.quran_line_spacing

        line_y_position -= settings.quran_line_spacing
        if settings.show_verse_numbers and last_quran_line is not None:
            marker_width, marker_height = settings.verse_number_resolution.as_tuple()
            markers.append(
                VerseMarker(
                    number=block.number,
                    x=(
                        last_quran_x
                        - settings.verse_number_x_offset
                        - marker_width
                    ),
                    y=(
                        line_y_position
                        - last_quran_line.height
                        + settings.verse_number_y_offset
                    ),
                    width=marker_width,
                    height=marker_height,
                )
            )

        if settings.translations:
            line_y_position += settings.quran_translation_spacing
            for translation in block.translations:
                for line in translation.lines:
                    line_y_position += line.height
                    if settings.translation_x_position == "center":
                        x_position = (width / 2) - (line.width // 2)
                    else:
                        x_position = settings.translation_x_position
                    positioned_lines.append(
                        PositionedLine(
                            line.text,
                            x_position,
                            line_y_position,
                            line.width,
                            line.height,
                            translation.style,
                        )
                    )
                    line_y_position += settings.translation_line_spacing
                line_y_position -= settings.translation_line_spacing
                line_y_position += settings.translation_language_spacing
            line_y_position -= settings.translation_language_spacing

        verse_y_position = line_y_position + settings.space_between_verses

    return ImageLayout(
        width=width,
        height=height,
        content_height=content_height,
        lines=tuple(positioned_lines),
        markers=tuple(markers),
    )
