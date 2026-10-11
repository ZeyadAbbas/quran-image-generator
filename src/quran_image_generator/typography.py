"""Presentation-only source boundaries and optional preferred whole-word breaks."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from .excerpts import Excerpt
from .layout import MeasuredLine, TextStyle, _wrap_words
from .references import ReferenceError, SourceSpan, resolve_span
from .scenes import Scene


def apply_break_hints(excerpt: Excerpt, scene: Scene, hints: list[dict[str, Any]], *, quotations: bool, verse_numbers: bool) -> Scene:
    if not hints:
        return scene
    layer = next(v for v in scene.layers if v.role == "arabic")
    cursor = len(layer.quote_open) + 1 if quotations and not layer.decoration_font else 0
    starts, ends = [], []
    for span in excerpt.spans:
        starts.append(cursor)
        cursor += len(span.text)
        if len(excerpt.spans) > 1 and verse_numbers and span.ends_ayah and span.source.surah:
            number = str(span.source.ayah)
            if layer.numeral_system == "arabic_indic":
                number = number.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
            cursor += 1 + len(layer.marker_prefix + number + layer.marker_suffix)
        ends.append(cursor)
        cursor += 1
    offsets: dict[int, str] = {}
    for index, hint in enumerate(hints):
        path = f"/line_breaks/{index}"
        occurrence, word = hint["span_occurrence"], hint["source_word"]
        if occurrence >= len(excerpt.spans):
            raise ReferenceError("invalid_break", "Break occurrence is absent", details={"path": path, "cue_id": excerpt.cue_id})
        span = excerpt.spans[occurrence]
        if not span.source.word_start <= word <= span.source.word_end:
            raise ReferenceError("invalid_break", "Break word is outside its occurrence", details={"path": path, "value": word})
        try:
            prefix = resolve_span(SourceSpan(span.source.surah, span.source.ayah, span.source.word_start, word))
        except ReferenceError as error:
            raise ReferenceError("invalid_break", "Break splits an indivisible source/display word group", details={"path": path, "source": hint, "cause": error.code}) from error
        offset = ends[occurrence] if word == span.source.word_end else starts[occurrence] + len(prefix.text)
        if (word == span.source.word_end and occurrence == len(excerpt.spans) - 1) or offset >= len(layer.text) or not layer.text[offset].isspace():
            raise ReferenceError("invalid_break", "A break must separate source words, with the ending marker attached", details={"path": path, "source": hint})
        if offset in offsets:
            raise ReferenceError("invalid_break", "Duplicate break at one source boundary", details={"path": path})
        offsets[offset] = hint["mode"]
    return replace(scene, layers=tuple(replace(v,
        forced_breaks=tuple(k for k, mode in offsets.items() if mode == "forced"),
        preferred_breaks=tuple(k for k, mode in offsets.items() if mode == "preferred")) if v.role == "arabic" else v for v in scene.layers))


def wrap_preferred(words: tuple[str, ...], style: TextStyle, measurer: Any, preferred: set[int], reserve: int = 0) -> tuple[MeasuredLine, ...]:
    if not preferred:
        return _wrap_words(words, style, measurer, final_line_reserve=reserve)
    result = []
    start = 0
    while start < len(words):
        end = start + 1
        while end < len(words):
            candidate = " ".join(words[start:end + 1])
            available = style.max_width - (reserve if end == len(words) - 1 else 0)
            if measurer.measure(candidate, style).visual_width > available:
                break
            end += 1
        if end < len(words):
            candidates = [i for i in preferred if start < i <= end]
            if candidates:
                end = max(candidates)
        text = " ".join(words[start:end])
        result.append(MeasuredLine(text, measurer.measure(text, style)))
        start = end
    return tuple(result)


def layout_paragraphs(text: str, forced: tuple[int, ...], preferred: tuple[int, ...]) -> list[tuple[str, set[int]]]:
    display = list(text)
    for offset in forced:
        display[offset] = "\n"
    text = "".join(display)
    result = []
    for paragraph in re.finditer(r"[^\n]+", text):
        tokens = list(re.finditer(r"\S+", paragraph.group()))
        indices = {sum(t.end() <= offset - paragraph.start() for t in tokens)
                   for offset in preferred if paragraph.start() <= offset < paragraph.end()}
        result.append((paragraph.group(), indices))
    return result
