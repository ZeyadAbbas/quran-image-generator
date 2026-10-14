"""Exact fill ownership from complete-line RAQM shaping, without word reshaping.

A private, ranged GPOS feature translates excluded glyphs outside a small ink
tile after normal substitution/positioning. Advances, outlines, text, font
selection and the approved layout are unchanged. Each decomposition must
reconstruct the ordinary raster exactly; shared clusters/ink become atomic.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from fontTools.otlLib.builder import buildLookup, buildSinglePos, buildValue
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables as ot
from PIL import Image, ImageChops, ImageDraw, ImageFont

from .backends import using_backend
from .excerpts import Excerpt
from .references import ReferenceError, bridge_data
from .render_cache import RenderCache
from .scenes import Layer, LayerPlan, layer_font
from .shaping import MixedMarkerFont, ShapedFont

TAG = "QIGW"
MAX_UNITS = 128
MAX_MASK_BYTES = 64 * 1024 * 1024
MAX_PROBES = 4096
_fonts: RenderCache[tuple, ImageFont.FreeTypeFont] = RenderCache(
    32, max_bytes=32 * 1024 * 1024
)
_nominal_ink: RenderCache[tuple, bool] = RenderCache(256)


def _has_nominal_outline(font: ImageFont.FreeTypeFont, character: str) -> bool:
    """Check glyph outlines without shaping an isolated source word/letter."""
    key = hashlib.sha256(font.font_bytes).hexdigest(), character
    cached = _nominal_ink.get(key)
    if cached is not None:
        return cached
    with TTFont(BytesIO(font.font_bytes)) as face:
        name = (face.getBestCmap() or {}).get(ord(character))
        glyphs = face.getGlyphSet()
        pen = BoundsPen(glyphs)
        if name:
            glyphs[name].draw(pen)
        box = pen.bounds
        result = bool(box and box[2] > box[0] and box[3] > box[1])
    _nominal_ink.put(key, result)
    return result


def error(code: str, message: str, **details: Any) -> ReferenceError:
    return ReferenceError(code, message, details={"path": "/word_emphasis", **details})


def _probe_font(font: ImageFont.FreeTypeFont, height: int) -> ImageFont.FreeTypeFont:
    data = font.font_bytes
    key = threading.get_ident(), hashlib.sha256(data).hexdigest(), font.size, height
    cached = _fonts.get(key)
    if cached is not None:
        return cached
    with TTFont(BytesIO(data)) as face:
        if "GPOS" not in face:
            face["GPOS"] = newTable("GPOS")
            table = face["GPOS"].table = ot.GPOS()
            table.Version = 0x10000
            table.ScriptList, table.FeatureList, table.LookupList = (
                ot.ScriptList(),
                ot.FeatureList(),
                ot.LookupList(),
            )
            table.ScriptList.ScriptRecord = []
            table.FeatureList.FeatureRecord = []
            table.LookupList.Lookup = []
            script = ot.ScriptRecord()
            script.ScriptTag, script.Script = "DFLT", ot.Script()
            script.Script.LangSysRecord, script.Script.LangSysCount = [], 0
            lang = script.Script.DefaultLangSys = ot.LangSys()
            (
                lang.LookupOrder,
                lang.ReqFeatureIndex,
                lang.FeatureIndex,
                lang.FeatureCount,
            ) = None, 0xFFFF, [], 0
            table.ScriptList.ScriptRecord.append(script)
            table.ScriptList.ScriptCount = 1
        table = face["GPOS"].table
        if any(record.FeatureTag == TAG for record in table.FeatureList.FeatureRecord):
            raise error(
                "unsupported_word_emphasis_font",
                "Font already uses the reserved word-mask feature",
                feature=TAG,
            )
        # Translate above the original tile. Use several legal int16 offsets
        # when unusually small fonts need more than one lookup.
        total = math.ceil((height + 16) * face["head"].unitsPerEm / font.size)
        count = math.ceil(total / 32767)
        if count > 32:
            raise error(
                "resource_limit", "Word-mask font needs too many positioning lookups"
            )
        indices = []
        for _ in range(count):
            shift = min(total, 32767)
            mapping = {
                name: buildValue({"YPlacement": shift}) for name in face.getGlyphOrder()
            }
            indices.append(len(table.LookupList.Lookup))
            table.LookupList.Lookup.append(
                buildLookup(buildSinglePos(mapping, face.getReverseGlyphMap()))
            )
            total -= shift
        table.LookupList.LookupCount = len(table.LookupList.Lookup)
        record = ot.FeatureRecord()
        record.FeatureTag, record.Feature = TAG, ot.Feature()
        record.Feature.FeatureParams = None
        record.Feature.LookupListIndex, record.Feature.LookupCount = (
            indices,
            len(indices),
        )
        added = len(table.FeatureList.FeatureRecord)
        table.FeatureList.FeatureRecord.append(record)
        # Feature records must be sorted. Remap every reference, including
        # variable-font feature substitutions, without changing any old lookup.
        ordered = sorted(
            enumerate(table.FeatureList.FeatureRecord),
            key=lambda item: item[1].FeatureTag,
        )
        remap = {old: new for new, (old, _) in enumerate(ordered)}
        table.FeatureList.FeatureRecord = [item for _, item in ordered]
        table.FeatureList.FeatureCount = len(ordered)
        for script_record in table.ScriptList.ScriptRecord:
            script = script_record.Script
            for lang in [
                script.DefaultLangSys,
                *(item.LangSys for item in script.LangSysRecord),
            ]:
                if lang is not None:
                    lang.FeatureIndex = sorted(
                        [*(remap[index] for index in lang.FeatureIndex), remap[added]]
                    )
                    lang.FeatureCount = len(lang.FeatureIndex)
                    if lang.ReqFeatureIndex != 0xFFFF:
                        lang.ReqFeatureIndex = remap[lang.ReqFeatureIndex]
        variations = getattr(table, "FeatureVariations", None)
        if variations:
            for variation in variations.FeatureVariationRecord:
                for (
                    replacement
                ) in variation.FeatureTableSubstitution.SubstitutionRecord:
                    replacement.FeatureIndex = remap[replacement.FeatureIndex]
        face.recalcTimestamp = False
        output = BytesIO()
        face.save(output)
    derived = output.getvalue()
    result = ImageFont.truetype(
        BytesIO(derived), font.size, layout_engine=ImageFont.Layout.RAQM
    )
    _fonts.put(key, result, size=len(derived))
    return result


@dataclass(frozen=True)
class MaskPart:
    bounds: tuple[int, int, int, int]
    alpha: bytes
    line_index: int
    run_id: str
    ranges: tuple[tuple[int, int], ...]
    text: str
    mask_font_sha256: str
    protected_pixels: int = 0

    def image(self) -> Image.Image:
        left, top, right, bottom = self.bounds
        return Image.frombytes("L", (right - left, bottom - top), self.alpha)


@dataclass
class WordUnit:
    members: list[dict[str, int | str]]
    ranges: list[tuple[int, int]]
    reasons: set[str] = field(default_factory=set)
    parts: list[MaskPart] = field(default_factory=list)


def source_units(
    excerpt: Excerpt, layer: Layer, *, quotations: bool, verse_numbers: bool
) -> list[WordUnit]:
    """Map verified bridge ranges into the actual decorated layer by construction."""
    elements = layer.decoration_layout == "elements"
    prefix = (
        layer.quote_open + " "
        if quotations and not layer.decoration_font and not elements
        else ""
    )
    pieces: list[str] = []
    units: list[WordUnit] = []
    cursor = len(prefix)
    digits = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
    for occurrence, span in enumerate(excerpt.spans):
        if pieces:
            cursor += 1
        record = bridge_data()["verses"][f"{span.source.surah}:{span.source.ayah}"]
        for group in record["groups"]:
            first, last, start, end = group[:4]
            if first < span.source.word_start or last > span.source.word_end:
                continue
            a, b = (
                start - span.character_start,
                min(end - span.character_start, len(span.text)),
            )
            if a < 0 or b <= a:
                continue
            members: list[dict[str, int | str]] = [
                {
                    "cue_id": excerpt.cue_id,
                    "span_occurrence": occurrence,
                    "surah": span.source.surah,
                    "ayah": span.source.ayah,
                    "source_word": word,
                }
                for word in range(first, last + 1)
            ]
            units.append(
                WordUnit(
                    members,
                    [(cursor + a, cursor + b)],
                    {"source_display_group"}
                    if first != last
                    or len(layer.text[cursor + a : cursor + b].split()) > 1
                    else set(),
                )
            )
        piece = span.text
        if (
            not elements
            and len(excerpt.spans) > 1
            and verse_numbers
            and span.ends_ayah
            and span.source.surah
        ):
            number = str(span.source.ayah)
            if layer.numeral_system == "arabic_indic":
                number = number.translate(digits)
            piece += " " + layer.marker_prefix + number + layer.marker_suffix
        pieces.append(piece)
        cursor += len(piece)
    expected = prefix + " ".join(pieces)
    if prefix:
        expected += " " + layer.quote_close
    if expected != layer.text:
        raise error(
            "word_mapping_mismatch",
            "Decorated layer no longer matches its verified source construction",
        )
    if not units or len(units) > MAX_UNITS:
        raise error(
            "resource_limit",
            f"Word emphasis supports 1..{MAX_UNITS} source/display groups per cue",
        )
    return units


@dataclass(frozen=True)
class PaintRun:
    text: str
    font: ShapedFont
    x: float
    y: float
    line_index: int
    run_id: str
    # actual rendered character index -> verified decorated-layer character index
    characters: tuple[int, ...]


def paint_runs(plan: LayerPlan) -> list[PaintRun]:
    """Visit the existing paint runs, retaining ordered character provenance."""
    tokens = list(re.finditer(r"\S+", plan.layer.text))
    token_index, runs = 0, []
    cursor: float = 0
    for line_index, (text, x, y) in enumerate(plan.lines):
        line_tokens = list(re.finditer(r"\S+", text))
        mapping = [-1] * len(text)
        for token in line_tokens:
            original = tokens[token_index]
            token_index += 1
            if token.group() != original.group():
                raise error(
                    "word_mapping_mismatch",
                    "Approved line does not preserve its ordered source/display tokens",
                )
            mapping[token.start() : token.end()] = range(
                original.start(), original.end()
            )
        if plan.layer.decoration_layout == "elements":
            body_cursor = 0
            for element in (
                item
                for item in plan.elements
                if item["line_index"] == line_index and item["kind"] == "body"
            ):
                value = element["text"]
                if text[body_cursor : body_cursor + len(value)] != value:
                    raise error(
                        "word_mapping_mismatch",
                        "Body element differs from approved line",
                    )
                font = layer_font(plan.layer, element["font_size"])
                if not isinstance(font, ShapedFont):
                    raise error(
                        "unsupported_word_emphasis_option",
                        "Unexpected mixed font in body element",
                    )
                runs.append(
                    PaintRun(
                        value,
                        font,
                        element["x"],
                        element["y"],
                        line_index,
                        element["id"],
                        tuple(mapping[body_cursor : body_cursor + len(value)]),
                    )
                )
                body_cursor += len(value) + 1
        else:
            font = layer_font(plan.layer, plan.font_size)
            if isinstance(font, MixedMarkerFont):
                # These are the exact same positions used by MixedMarkerFont.paint.
                cursor = (
                    x + font.getbbox(text)[2] if font.primary.direction == "rtl" else x
                )
                offset = 0
                starts = []
                for part in font.pattern.split(text):
                    if part.strip():
                        starts.append(offset + len(part) - len(part.lstrip()))
                    offset += len(part)
                for start, (value, face, box, gap) in zip(
                    starts, font._runs(text), strict=True
                ):
                    if font.primary.direction == "rtl":
                        cursor -= box[2] - box[0] + gap
                    if face is font.primary:
                        runs.append(
                            PaintRun(
                                value,
                                face,
                                cursor - box[0] + gap / 2,
                                y,
                                line_index,
                                f"line:{line_index}:{start}",
                                tuple(mapping[start : start + len(value)]),
                            )
                        )
                    if font.primary.direction != "rtl":
                        cursor += box[2] - box[0] + gap
            else:
                runs.append(
                    PaintRun(
                        text,
                        font,
                        x,
                        y,
                        line_index,
                        f"line:{line_index}",
                        tuple(mapping),
                    )
                )
    if token_index != len(tokens):
        raise error(
            "word_mapping_mismatch", "Approved lines omit displayed source tokens"
        )
    return runs


class RunProbe:
    def __init__(self, run: PaintRun, checkpoint: Callable[[], None]) -> None:
        self.checkpoint = checkpoint
        checkpoint()
        if run.font.pillow is None or run.font.tracking:
            raise error(
                "unsupported_word_emphasis_option",
                "Word emphasis needs an untracked Pillow RAQM body font",
            )
        self.run = run
        left, top, right, bottom = run.font._bbox(run.text)
        if right - left > 16384 or bottom - top > 4096:
            raise error(
                "resource_limit", "Word-mask raster exceeds the bounded line tile"
            )
        self.scale = run.font.horizontal_scale
        self.xy: tuple[float, float]
        if self.scale != 1:
            self.size = max(1, round(right - left) + 4), max(1, round(bottom - top) + 4)
            self.xy = round(2 - left), round(2 - top)
            self.offset = (0, 0)
        else:
            ox, oy = math.floor(run.x + left) - 4, math.floor(run.y + top) - 4
            self.size = (
                math.ceil(run.x + right) - ox + 4,
                math.ceil(run.y + bottom) - oy + 4,
            )
            self.xy = run.x - ox, run.y - oy
            self.offset = ox, oy
        self.font = _probe_font(run.font.pillow, self.size[1])
        self.font_sha256 = hashlib.sha256(self.font.font_bytes).hexdigest()
        self.original = self._draw(run.font.pillow, run.font.options)
        self.ink = self.original.getbbox()
        neutral = self._draw(
            self.font,
            {
                **run.font.options,
                "features": [*run.font.options.get("features", []), TAG + "=0"],
            },
        )
        with neutral, ImageChops.difference(neutral, self.original) as difference:
            unsafe = bool(difference.getbbox())
        if unsafe:
            raise error(
                "unsafe_word_mask",
                "Private positioning changed the neutral full-line raster",
            )

    def _draw(self, font: ImageFont.FreeTypeFont, options: dict) -> Image.Image:
        result = Image.new("L", self.size)
        ImageDraw.Draw(result).text(
            self.xy,
            self.run.text,
            font=font,
            fill=255,
            anchor="ls",
            direction=self.run.font.direction,
            **options,
        )
        return result

    def mask(self, ranges: list[tuple[int, int]]) -> Image.Image:
        self.checkpoint()
        # Invisible separators can be positioning parents. They must not move
        # and drag a selected mark even though they contribute no fill ink.
        intervals = sorted(
            [
                *ranges,
                *((i, i + 1) for i, ch in enumerate(self.run.text) if ch.isspace()),
            ]
        )
        merged: list[tuple[int, int]] = []
        for a, b in intervals:
            if merged and a <= merged[-1][1]:
                merged[-1] = merged[-1][0], max(b, merged[-1][1])
            else:
                merged.append((a, b))
        features = [*self.run.font.options.get("features", []), TAG + "=0"]
        cursor = 0
        for a, b in merged:
            if a > cursor:
                features.append(f"{TAG}[{cursor}:{a}]=1")
            cursor = b
        if cursor < len(self.run.text):
            features.append(f"{TAG}[{cursor}:{len(self.run.text)}]=1")
        raw = self._draw(self.font, {**self.run.font.options, "features": features})
        if ImageChops.subtract(raw, self.original).getbbox():
            # Any shifted glyph arriving in another word's tile is a hard error.
            raise error(
                "unsafe_word_mask", "Ranged positioning changed visible glyph ink"
            )
        return raw

    def placed(self, mask: Image.Image) -> tuple[Image.Image, tuple[int, int]]:
        if self.scale == 1 or not self.ink:
            return mask.copy(), self.offset
        crop = mask.crop(self.ink)
        scaled = crop.resize(
            (max(1, round(crop.width * self.scale)), crop.height),
            Image.Resampling.LANCZOS,
        )
        crop.close()
        bx, by = self.xy
        return scaled, (
            round(self.run.x + (self.ink[0] - bx) * self.scale),
            round(self.run.y + self.ink[1] - by),
        )


def _intervals(characters: tuple[int, ...], unit: WordUnit) -> list[tuple[int, int]]:
    indices = [
        i
        for i, point in enumerate(characters)
        if point >= 0 and any(a <= point < b for a, b in unit.ranges)
    ]
    result: list[tuple[int, int]] = []
    for index in indices:
        if result and result[-1][1] == index:
            result[-1] = result[-1][0], index + 1
        else:
            result.append((index, index + 1))
    return result


def _overlap(a: Image.Image, b: Image.Image) -> bool:
    ab, bb = a.getbbox(), b.getbbox()
    if not ab or not bb:
        return False
    box = max(ab[0], bb[0]), max(ab[1], bb[1]), min(ab[2], bb[2]), min(ab[3], bb[3])
    if box[0] >= box[2] or box[1] >= box[3]:
        return False
    with a.crop(box) as x, b.crop(box) as y:
        return (
            ImageChops.multiply(
                x.point(lambda v: 255 if v else 0), y.point(lambda v: 255 if v else 0)
            ).getbbox()
            is not None
        )


def extract_units(
    excerpt: Excerpt,
    plan: LayerPlan,
    *,
    quotations: bool,
    verse_numbers: bool,
    checkpoint: Callable[[], None] | None = None,
) -> list[WordUnit]:
    units = source_units(
        excerpt, plan.layer, quotations=quotations, verse_numbers=verse_numbers
    )
    parents = list(range(len(units)))
    operations = 0
    mask_bytes = 0

    def bounded_probe() -> None:
        nonlocal operations
        operations += 1
        if operations > MAX_PROBES:
            raise error("resource_limit", "Word-mask probe budget exceeded")
        if checkpoint is not None:
            checkpoint()

    def root(i: int) -> int:
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    def join(indices: list[int], reason: str) -> None:
        head = root(indices[0])
        for index in indices:
            other = root(index)
            if other != head:
                units[head].reasons.update(units[other].reasons)
                parents[other] = head
            units[head].reasons.add(reason)

    for run in paint_runs(plan):
        probe = RunProbe(run, bounded_probe)
        selected = [
            (i, _intervals(run.characters, unit)) for i, unit in enumerate(units)
        ]
        selected = [(i, ranges) for i, ranges in selected if ranges]
        if not selected:
            continue
        if probe.size[0] * probe.size[1] * (len(selected) + 20) > MAX_MASK_BYTES:
            raise error("resource_limit", "Word-mask working set exceeds 64 MiB")
        all_ranges = [value for _, ranges in selected for value in ranges]
        owned = {i for a, b in all_ranges for i in range(a, b)}
        # HarfBuzz can assign a cross-space ligature to its first character.
        # Its two word masks then look disjoint even though the next word's
        # initial letter was consumed. Probe that boundary in the full run;
        # never mistake the missing initial for an independently paintable split.
        for position, (index, ranges) in enumerate(selected):
            initial = next(
                (i for a, b in ranges for i in range(a, b) if run.text[i].isalpha()),
                None,
            )
            if initial is None:
                continue
            with probe.mask([(ranges[0][0], initial + 1)]) as initial_ink:
                visible = bool(initial_ink.getbbox())
            if visible or not _has_nominal_outline(probe.font, run.text[initial]):
                continue
            previous = selected[position - 1] if position else None
            if previous is None or any(
                not run.text[i].isspace() and i not in owned
                for i in range(previous[1][-1][1], initial)
            ):
                raise error(
                    "word_decoration_atomic",
                    "A source-word initial belongs to an unresolved static/word shaping boundary",
                    members=units[index].members,
                    line_index=run.line_index,
                    run_id=run.run_id,
                )
            join([previous[0], index], "shaping_cluster")
        body = probe.mask(all_ranges)
        # A shared source/decorative glyph cannot be recolored independently.
        fixed_ranges = [(i, i + 1) for i in range(len(run.text)) if i not in owned]
        fixed = probe.mask(fixed_ranges)
        if ImageChops.difference(ImageChops.add(body, fixed), probe.original).getbbox():
            raise error(
                "word_decoration_atomic",
                "Word and decoration ink cannot be separated safely",
                line_index=run.line_index,
                run_id=run.run_id,
            )
        groups = [([i], ranges, probe.mask(ranges)) for i, ranges in selected]
        while True:
            merged = False
            for i in range(len(groups)):
                for j in range(i + 1, len(groups)):
                    if _overlap(groups[i][2], groups[j][2]):
                        members = groups[i][0] + groups[j][0]
                        ranges = groups[i][1] + groups[j][1]
                        join(members, "overlapping_ink")
                        groups[i] = members, ranges, probe.mask(ranges)
                        del groups[j]
                        merged = True
                        break
                if merged:
                    break
            if merged:
                continue
            combined = Image.new("L", body.size)
            for _, _, mask in groups:
                combined = ImageChops.add(combined, mask)
            missing = ImageChops.difference(body, combined)
            if not missing.getbbox():
                break
            # A glyph cluster/attachment can cross a source-unit boundary. Find
            # the smallest contiguous selection restoring that shared ink.
            for length in range(2, len(groups) + 1):
                for start in range(len(groups) - length + 1):
                    chunk = groups[start : start + length]
                    members = [i for indices, _, _ in chunk for i in indices]
                    ranges = [
                        r for _, selected_ranges, _ in chunk for r in selected_ranges
                    ]
                    joint = probe.mask(ranges)
                    if _overlap(joint, missing):
                        join(members, "shaping_cluster")
                        groups[start : start + length] = [(members, ranges, joint)]
                        merged = True
                        break
                if merged:
                    break
            if not merged:
                raise error(
                    "unsafe_word_mask",
                    "Word masks do not reconstruct the approved full-line ink",
                    line_index=run.line_index,
                    run_id=run.run_id,
                )
        reference, _ = probe.placed(body)
        fixed_placed, _ = probe.placed(fixed)
        free = fixed_placed.point(lambda value: 0 if value else 255)
        for members, ranges, mask in groups:
            placed, offset = probe.placed(mask)
            # Scaling can produce rounding/ringing at adjoining ink. Record
            # ownership using the unchanged combined reference alpha.
            support = placed.point(lambda value: 255 if value else 0)
            exact = ImageChops.multiply(reference, support)
            box = exact.getbbox()
            if box:
                # Static inline decoration ink has precedence in shared pixels.
                # Keep the complete word bounds for backgrounds/provenance.
                paintable = ImageChops.multiply(exact, free)
                with paintable.crop(box) as crop:
                    bounds = (
                        box[0] + offset[0],
                        box[1] + offset[1],
                        box[2] + offset[0],
                        box[3] + offset[1],
                    )
                    part = MaskPart(
                        bounds,
                        crop.tobytes(),
                        run.line_index,
                        run.run_id,
                        tuple(ranges),
                        run.text,
                        probe.font_sha256,
                        sum(
                            1
                            for a, b in zip(
                                exact.crop(box).tobytes(), crop.tobytes(), strict=True
                            )
                            if a and not b
                        ),
                    )
                    mask_bytes += len(part.alpha)
                    if mask_bytes > MAX_MASK_BYTES:
                        raise error(
                            "resource_limit", "Word-mask storage exceeds 64 MiB"
                        )
                    units[members[0]].parts.append(part)
        reference.close()
    # Horizontal resampling and intentional line/run overlaps can share ink
    # after placement. Such owners must receive the same paint weight too.
    for i, a in enumerate(units):
        for j in range(i + 1, len(units)):
            if root(i) == root(j):
                continue
            for ap in a.parts:
                for bp in units[j].parts:
                    box = (
                        max(ap.bounds[0], bp.bounds[0]),
                        max(ap.bounds[1], bp.bounds[1]),
                        min(ap.bounds[2], bp.bounds[2]),
                        min(ap.bounds[3], bp.bounds[3]),
                    )
                    if box[0] < box[2] and box[1] < box[3]:
                        with ap.image() as am, bp.image() as bm:
                            ac = am.crop(
                                (
                                    box[0] - ap.bounds[0],
                                    box[1] - ap.bounds[1],
                                    box[2] - ap.bounds[0],
                                    box[3] - ap.bounds[1],
                                )
                            )
                            bc = bm.crop(
                                (
                                    box[0] - bp.bounds[0],
                                    box[1] - bp.bounds[1],
                                    box[2] - bp.bounds[0],
                                    box[3] - bp.bounds[1],
                                )
                            )
                            if _overlap(ac, bc):
                                join([i, j], "overlapping_ink")
    result: dict[int, WordUnit] = {}
    for index, unit in enumerate(units):
        owner = root(index)
        combined_unit = result.setdefault(
            owner, WordUnit([], [], set(units[owner].reasons))
        )
        combined_unit.members.extend(unit.members)
        combined_unit.ranges.extend(unit.ranges)
        combined_unit.parts.extend(unit.parts)
    for unit in result.values():
        if not unit.parts or not any(any(part.alpha) for part in unit.parts):
            raise error(
                "word_decoration_atomic" if unit.parts else "unpaintable_source_word",
                "Source group has no independently paintable ink",
                members=unit.members,
            )
    return list(result.values())


def word_units(
    excerpt: Excerpt,
    plan: LayerPlan,
    backend: str,
    *,
    quotations: bool,
    verse_numbers: bool,
    checkpoint: Callable[[], None] | None = None,
) -> list[WordUnit]:
    if backend != "pillow":
        raise error(
            "unsupported_word_emphasis_backend",
            "Layout-stable word emphasis currently requires Pillow RAQM",
            backend=backend,
        )
    if (
        plan.status != "ready"
        or plan.layer.direction != "rtl"
        or plan.layer.kind != "text"
    ):
        raise error(
            "unsupported_word_emphasis_option",
            "Word emphasis requires a visible RTL Arabic text layer",
        )
    with using_backend(backend):
        return extract_units(
            excerpt,
            plan,
            quotations=quotations,
            verse_numbers=verse_numbers,
            checkpoint=checkpoint,
        )
