"""Pure text measurement and positioning for generated images."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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
class Bounds:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


class LayoutOverflowError(ValueError):
    """Raised before rendering when configured content would be clipped."""

    def __init__(
        self,
        element: str,
        axis: Literal["horizontal", "vertical"],
        actual: tuple[float, float],
        allowed: tuple[float, float],
    ) -> None:
        self.element = element
        self.axis = axis
        self.actual = actual
        self.allowed = allowed
        self.overflow = max(
            allowed[0] - actual[0],
            actual[1] - allowed[1],
            0,
        )
        super().__init__(
            f"{element} exceeds {axis} bounds by {self.overflow:g}px "
            f"({actual[0]:g}..{actual[1]:g}; allowed "
            f"{allowed[0]:g}..{allowed[1]:g})"
        )


@dataclass(frozen=True, slots=True)
class ImageLayout:
    width: int
    height: int
    content_height: float
    lines: tuple[PositionedLine, ...]
    markers: tuple[VerseMarker, ...]
    content_bounds: Bounds | None = None


@dataclass(frozen=True, slots=True)
class _TranslationBlock:
    resource_id: str
    block: TextBlock


@dataclass(frozen=True, slots=True)
class _VerseBlock:
    number: int
    key: str
    quran: TextBlock
    translations: tuple[_TranslationBlock, ...]


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


def _block_height(lines: tuple[MeasuredLine, ...], spacing: int) -> float:
    if not lines:
        return 0
    return sum(line.height for line in lines) + spacing * (len(lines) - 1)


def _wrap_words(
    words: tuple[str, ...],
    style: TextStyle,
    measurer: Any,
    *,
    final_line_reserve: int = 0,
) -> tuple[MeasuredLine, ...]:
    """Greedily wrap without emitting empty lines or splitting a token.

    A token wider than its available line remains intact on its own line. The
    complete layout validation then reports it as an actionable overflow rather
    than silently dropping, truncating, or splitting language-dependent text.
    """

    normalized_words = tuple(word for word in words if word)
    lines: list[MeasuredLine] = []
    current_line = ""

    for index, word in enumerate(normalized_words):
        candidate = (
            current_line + style.word_spacing + word if current_line else word
        )
        candidate_metrics = _measure_line(candidate, style, measurer)
        available_width = style.max_width
        if index == len(normalized_words) - 1:
            available_width -= final_line_reserve

        if not current_line or candidate_metrics.width <= available_width:
            current_line = candidate
            continue

        lines.append(_measure_line(current_line, style, measurer))
        current_line = word

    if current_line:
        lines.append(_measure_line(current_line, style, measurer))
    return tuple(lines)


def _marker_reserve(settings: Settings) -> int:
    if not settings.show_verse_numbers:
        return 0
    return max(
        0,
        settings.verse_number_resolution.width
        + settings.verse_number_x_offset,
    )


def layout_quran_text(
    words: tuple[str, ...], settings: Settings, measurer: Any
) -> TextBlock:
    style = _quran_style(settings)
    measured_lines = _wrap_words(
        words,
        style,
        measurer,
        final_line_reserve=_marker_reserve(settings),
    )
    return TextBlock(
        lines=measured_lines,
        height=_block_height(measured_lines, settings.quran_line_spacing),
        style=style,
    )


def layout_translation_text(
    translation: VerseTranslation,
    settings: Settings,
    measurer: Any,
) -> TextBlock:
    translation_settings = next(
        item
        for item in settings.translations
        if item.resource_id == translation.resource_id
    )
    style = _translation_style(settings, translation_settings)
    measured_lines = _wrap_words(
        tuple(translation.text.split()),
        style,
        measurer,
    )
    return TextBlock(
        lines=measured_lines,
        height=_block_height(measured_lines, settings.translation_line_spacing),
        style=style,
    )


def _validate_interval(
    element: str,
    axis: Literal["horizontal", "vertical"],
    actual: tuple[float, float],
    allowed: tuple[float, float],
) -> None:
    if actual[0] < allowed[0] or actual[1] > allowed[1]:
        raise LayoutOverflowError(element, axis, actual, allowed)


def _validate_block_width(
    block: TextBlock,
    element: str,
    *,
    final_line_reserve: int = 0,
) -> None:
    for index, line in enumerate(block.lines):
        available_width = block.style.max_width
        if index == len(block.lines) - 1:
            available_width -= final_line_reserve
        _validate_interval(
            f"{element} line {index + 1}",
            "horizontal",
            (0, line.width),
            (0, available_width),
        )


def _layout_verse(
    verse: Verse, settings: Settings, measurer: Any
) -> _VerseBlock:
    quran = layout_quran_text(verse.words, settings, measurer)
    _validate_block_width(
        quran,
        f"Quran text for verse {verse.key or verse.number}",
        final_line_reserve=_marker_reserve(settings),
    )

    translations: list[_TranslationBlock] = []
    for translation in verse.translations:
        block = layout_translation_text(translation, settings, measurer)
        _validate_block_width(
            block,
            (
                f"translation {translation.resource_id} for verse "
                f"{verse.key or verse.number}"
            ),
        )
        translations.append(_TranslationBlock(translation.resource_id, block))

    return _VerseBlock(
        number=verse.number,
        key=verse.key,
        quran=quran,
        translations=tuple(translations),
    )


def _horizontal_x(
    canvas_width: int,
    line_width: float,
    position: int | Literal["center"],
    *,
    right_aligned: bool,
) -> float:
    if position == "center":
        # Keep the legacy one-pixel tie break when the widths have mixed parity.
        return (canvas_width // 2) - (line_width // 2)
    if right_aligned:
        return canvas_width - position - line_width
    return position


def _position_text_block(
    block: TextBlock,
    *,
    top: float,
    spacing: int,
    canvas_width: int,
    position: int | Literal["center"],
    right_aligned: bool,
    element: str,
    positioned_lines: list[PositionedLine],
) -> tuple[float, PositionedLine | None]:
    baseline = top
    last_positioned: PositionedLine | None = None

    for index, line in enumerate(block.lines):
        baseline += line.height
        x_position = _horizontal_x(
            canvas_width,
            line.width,
            position,
            right_aligned=right_aligned,
        )
        _validate_interval(
            f"{element} line {index + 1}",
            "horizontal",
            (x_position, x_position + line.width),
            (0, canvas_width),
        )
        last_positioned = PositionedLine(
            line.text,
            x_position,
            baseline,
            line.width,
            line.height,
            block.style,
        )
        positioned_lines.append(last_positioned)
        baseline += spacing

    if block.lines:
        baseline -= spacing
    return baseline, last_positioned


def _content_bounds(
    lines: tuple[PositionedLine, ...], markers: tuple[VerseMarker, ...]
) -> Bounds | None:
    if not lines and not markers:
        return None

    left_edges = [line.x for line in lines] + [marker.x for marker in markers]
    top_edges = [line.y - line.height for line in lines] + [
        marker.y for marker in markers
    ]
    right_edges = [line.x + line.width for line in lines] + [
        marker.x + marker.width for marker in markers
    ]
    bottom_edges = [line.y for line in lines] + [
        marker.y + marker.height for marker in markers
    ]
    return Bounds(
        min(left_edges),
        min(top_edges),
        max(right_edges),
        max(bottom_edges),
    )


def _shift_vertical(
    lines: tuple[PositionedLine, ...],
    markers: tuple[VerseMarker, ...],
    amount: float,
) -> tuple[tuple[PositionedLine, ...], tuple[VerseMarker, ...]]:
    shifted_lines = tuple(
        PositionedLine(
            line.text,
            line.x,
            line.y + amount,
            line.width,
            line.height,
            line.style,
        )
        for line in lines
    )
    shifted_markers = tuple(
        VerseMarker(
            marker.number,
            marker.x,
            marker.y + amount,
            marker.width,
            marker.height,
        )
        for marker in markers
    )
    return shifted_lines, shifted_markers


def build_layout(
    passage: Passage, settings: Settings, measurer: Any
) -> ImageLayout:
    """Build a validated draw plan without rendering or other I/O.

    Layout bounds use measured floating-point metrics. The Wand adapter draws at
    integer coordinates, so its outer edges may differ by less than one pixel.
    """

    width, height = settings.resolution.as_tuple()
    verse_blocks = tuple(
        _layout_verse(verse, settings, measurer) for verse in passage.verses
    )
    if not verse_blocks:
        return ImageLayout(width, height, 0, (), (), None)

    positioned_lines: list[PositionedLine] = []
    markers: list[VerseMarker] = []
    current_y = 0.0

    for verse_index, block in enumerate(verse_blocks):
        quran_bottom, last_quran_line = _position_text_block(
            block.quran,
            top=current_y,
            spacing=settings.quran_line_spacing,
            canvas_width=width,
            position=settings.quran_x_position,
            right_aligned=True,
            element=f"Quran text for verse {block.key or block.number}",
            positioned_lines=positioned_lines,
        )

        if settings.show_verse_numbers and last_quran_line is not None:
            marker_width, marker_height = settings.verse_number_resolution.as_tuple()
            marker = VerseMarker(
                number=block.number,
                x=(
                    last_quran_line.x
                    - settings.verse_number_x_offset
                    - marker_width
                ),
                y=(
                    last_quran_line.y
                    - last_quran_line.height
                    + settings.verse_number_y_offset
                ),
                width=marker_width,
                height=marker_height,
            )
            _validate_interval(
                f"verse marker {block.key or block.number}",
                "horizontal",
                (marker.x, marker.x + marker.width),
                (0, width),
            )
            markers.append(marker)

        current_y = quran_bottom
        if block.translations:
            current_y += settings.quran_translation_spacing
            for translation_index, translation in enumerate(block.translations):
                if translation_index:
                    current_y += settings.translation_language_spacing
                current_y, _ = _position_text_block(
                    translation.block,
                    top=current_y,
                    spacing=settings.translation_line_spacing,
                    canvas_width=width,
                    position=settings.translation_x_position,
                    right_aligned=False,
                    element=(
                        f"translation {translation.resource_id} for verse "
                        f"{block.key or block.number}"
                    ),
                    positioned_lines=positioned_lines,
                )

        if verse_index < len(verse_blocks) - 1:
            current_y += settings.space_between_verses

    local_lines = tuple(positioned_lines)
    local_markers = tuple(markers)
    local_bounds = _content_bounds(local_lines, local_markers)
    if local_bounds is None:
        return ImageLayout(width, height, 0, (), (), None)

    target_top = (
        (height - local_bounds.height) // 2
    ) + settings.total_y_offset
    shifted_lines, shifted_markers = _shift_vertical(
        local_lines,
        local_markers,
        target_top - local_bounds.top,
    )
    shifted_bounds = _content_bounds(shifted_lines, shifted_markers)
    if shifted_bounds is None:  # pragma: no cover - guarded by local_bounds
        return ImageLayout(width, height, 0, (), (), None)
    _validate_interval(
        "content",
        "vertical",
        (shifted_bounds.top, shifted_bounds.bottom),
        (0, height),
    )

    return ImageLayout(
        width=width,
        height=height,
        content_height=shifted_bounds.height,
        lines=shifted_lines,
        markers=shifted_markers,
        content_bounds=shifted_bounds,
    )
