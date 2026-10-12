"""Whole-word shaped wrapping, stable baselines and actionable fit diagnostics."""

from __future__ import annotations

import copy
import math
from dataclasses import replace
from typing import TYPE_CHECKING

from .layout import MeasuredLine, TextMetrics, TextStyle
from .references import ReferenceError

if TYPE_CHECKING:
    from .scenes import Layer, LayerPlan, Scene
    from .shaping import MixedMarkerFont, ShapedFont


class FitError(ReferenceError):
    def __init__(
        self,
        role: str,
        bounds: tuple[int, int, int, int],
        allowed: tuple[int, ...],
        size: int | float,
        line_count: int,
    ) -> None:
        self.details = {
            "role": role,
            "bounds": bounds,
            "allowed": allowed,
            "font_size": size,
            "line_count": line_count,
            "constraint": "allowed_region_or_line_count",
            "overflow": {"left": max(0, allowed[0] - bounds[0]), "top": max(0, allowed[1] - bounds[1]),
                         "right": max(0, bounds[2] - allowed[2]), "bottom": max(0, bounds[3] - allowed[3])},
            "suggestions": [
                "split_cue",
                "enlarge_region",
                "choose_smaller_preferred_font",
            ],
        }
        super().__init__(
            "layout_overflow",
            f"{role} does not fit its region at the readable minimum; split the cue or enlarge the region",
        )


class _Measurer:
    def __init__(self, font: ShapedFont | MixedMarkerFont) -> None:
        self.font = font

    def measure(self, text: str, style: TextStyle) -> TextMetrics:
        left, top, right, bottom = self.font.getbbox(text)
        return TextMetrics(
            right - left,
            bottom - top,
            max(0, -top),
            max(0, bottom),
            max(0, -top),
            max(0, bottom),
            left,
            right,
        )


def pixel_region(scene: Scene, layer: Layer) -> tuple[int, int, int, int]:
    return tuple(
        round(v * (scene.width if i % 2 == 0 else scene.height))
        for i, v in enumerate(layer.region)
    )  # type: ignore[return-value]


def within(bounds: tuple[int, int, int, int], allowed: tuple[int, ...]) -> bool:
    return (
        bounds[0] >= allowed[0]
        and bounds[1] >= allowed[1]
        and bounds[2] <= allowed[2]
        and bounds[3] <= allowed[3]
    )


def plan_text(scene: Scene, layer: Layer, digest: str, *, preferred_size: float | None = None) -> LayerPlan:
    if layer.decoration_layout == "elements":
        from .decoration_elements import plan_elements

        return plan_elements(scene, layer, digest, preferred_size=preferred_size)
    from .scenes import LayerPlan, check_glyphs, layer_font

    check_glyphs(layer)
    decoration = (
        replace(
            layer,
            font=layer.decoration_font,
            resolved_font="", resolved_font_sha256="", variation_axes={}, font_face=0, font_fallbacks=(), font_features=(), font_language="",
            text=layer.suffix
            + "".join(layer.inline_markers)
            + (layer.quote_open + layer.quote_close if layer.ornaments else ""),
            suffix="",
            decoration_font="",
            inline_markers=(),
            horizontal_scale=1,
        )
        if layer.decoration_font
        else layer
    )
    decoration_digest = ""
    if layer.decoration_font:
        from .scenes import checked_asset

        decoration_digest = checked_asset(
            layer.decoration_font, layer.decoration_sha256
        )
        check_glyphs(decoration)
    from .scenes import dimension_scale

    scale = dimension_scale(scene, layer)
    preferred = max(
        1,
        round(layer.font_size * scale, 2)
        if isinstance(layer.font_size, float)
        else round(layer.font_size * scale),
    )
    if preferred_size is not None:
        preferred = preferred_size
    minimum = max(1, round(layer.min_font_size * scale))
    allowed = pixel_region(scene, layer)
    padding = math.ceil(
        (layer.outline_width + 4 * layer.shadow_blur + layer.safe_margin) * scale
    )
    dx, dy = (v * scale for v in layer.shadow_offset)
    last_bounds = (0, 0, 0, 0)
    last_count = 0
    sizes = (
        tuple(
            max(minimum, preferred - n)
            for n in range(math.ceil(preferred - minimum) + 1)
        )
        if layer.fit == "shrink"
        else (preferred,)
    )
    for size in sizes:
        font = layer_font(layer, size)
        decoration_font = layer_font(decoration, size * layer.decoration_scale)
        quote_boxes = (
            tuple(
                decoration_font.getbbox(text)
                for text in (layer.quote_open, layer.quote_close)
            )
            if layer.ornaments
            else ((0, 0, 0, 0), (0, 0, 0, 0))
        )
        quote_widths = tuple(
            box[2] - box[0] + layer.quote_spacing * scale if layer.ornaments else 0
            for box in quote_boxes
        )
        marker_size = max(1, round(size * layer.suffix_scale))
        marker_box = (
            layer_font(decoration, marker_size).getbbox(layer.suffix)
            if layer.suffix
            else (0, 0, 0, 0)
        )
        reserve = (
            math.ceil(marker_box[2] - marker_box[0] + layer.suffix_spacing * scale)
            if layer.suffix
            else 0
        )
        style = TextStyle(
            layer.font,
            size,
            layer.color,
            0,
            max(
                1,
                allowed[2]
                - allowed[0]
                - padding * 2
                - math.ceil(abs(dx))
                - math.ceil(sum(quote_widths)),
            ),
            " ",
        )
        lines: list[MeasuredLine] = []
        from .typography import layout_paragraphs, wrap_preferred

        for paragraph, preferred_breaks in layout_paragraphs(layer.text, layer.forced_breaks, layer.preferred_breaks):
            words = paragraph.split()
            if words and words[0] == layer.quote_open and len(words) > 1:
                words[:2] = [" ".join(words[:2])]
                preferred_breaks = {max(1, i - 1) for i in preferred_breaks}
            if words and words[-1] == layer.quote_close and len(words) > 1:
                words[-2:] = [" ".join(words[-2:])]
            lines.extend(
                wrap_preferred(
                    tuple(words), style, _Measurer(font), preferred_breaks, reserve
                )
            )
        if not lines:
            raise ReferenceError("missing_asset", f"{layer.role} has no visible text")
        step = size * layer.line_height if layer.line_height else max(line.metrics.height for line in lines) + layer.line_spacing * scale
        positioned = []
        boxes = []
        for index, line in enumerate(lines):
            y = (
                layer.anchor[1] * scene.height
                + (index - (len(lines) - 1 if layer.baseline_anchor == "last" else 0))
                * step
            )
            if layer.alignment == "center":
                x = (
                    layer.anchor[0] * scene.width
                    - (line.left_offset + line.right_offset) / 2
                )
                x += (
                    (quote_widths[1] if index == len(lines) - 1 else 0)
                    - (quote_widths[0] if index == 0 else 0)
                ) / 2
            elif layer.alignment == "right":
                x = allowed[2] - padding - line.right_offset
            else:
                x = allowed[0] + padding - line.left_offset
            positioned.append((line.text, x, y))
            boxes.append(
                (
                    math.floor(x + line.left_offset),
                    math.floor(y - line.metrics.visual_top_extent),
                    math.ceil(x + line.right_offset),
                    math.ceil(y + line.metrics.visual_bottom_extent),
                )
            )
        suffix_position = None
        ornament_positions = []
        if layer.ornaments:
            for index, (text, box, qwidth) in enumerate(
                zip(
                    (layer.quote_open, layer.quote_close),
                    quote_boxes,
                    quote_widths,
                    strict=True,
                )
            ):
                line_index = 0 if index == 0 else len(lines) - 1
                ink = boxes[line_index]
                qx = (
                    (ink[2] + layer.quote_spacing * scale - box[0])
                    if index == 0
                    else (ink[0] - qwidth - box[0])
                )
                qy = positioned[line_index][2]
                ornament_positions.append((text, qx, qy))
                boxes.append(
                    (
                        math.floor(qx + box[0]),
                        math.floor(qy + box[1]),
                        math.ceil(qx + box[2]),
                        math.ceil(qy + box[3]),
                    )
                )
        if layer.suffix:
            last = boxes[-1] if layer.ornaments else boxes[len(lines) - 1]
            sx = last[0] - reserve - marker_box[0]
            sy = positioned[-1][2] + layer.suffix_offset * scale
            suffix_position = (sx, sy, marker_size)
            boxes.append(
                (
                    math.floor(sx + marker_box[0]),
                    math.floor(sy + marker_box[1]),
                    math.ceil(sx + marker_box[2]),
                    math.ceil(sy + marker_box[3]),
                )
            )
        bounds = (
            math.floor(min(b[0] for b in boxes) - padding + min(0, dx)),
            math.floor(min(b[1] for b in boxes) - padding + min(0, dy)),
            math.ceil(max(b[2] for b in boxes) + padding + max(0, dx)),
            math.ceil(max(b[3] for b in boxes) + padding + max(0, dy)),
        )
        glyph_bounds = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
        from .anchoring import anchor_offset

        ax, ay = anchor_offset(scene, layer, glyph_bounds, bounds)
        if ax or ay:
            positioned = [(text, x + ax, y + ay) for text, x, y in positioned]
            bounds = (bounds[0] + ax, bounds[1] + ay, bounds[2] + ax, bounds[3] + ay)
            glyph_bounds = (glyph_bounds[0] + ax, glyph_bounds[1] + ay, glyph_bounds[2] + ax, glyph_bounds[3] + ay)
            if suffix_position:
                suffix_position = (suffix_position[0] + ax, suffix_position[1] + ay, suffix_position[2])
            ornament_positions = [(text, x + ax, y + ay) for text, x, y in ornament_positions]
        last_bounds, last_count = bounds, len(lines)
        collisions = [(i - 1, i) for i in range(1, len(lines)) if boxes[i - 1][3] + padding > boxes[i][1] - padding] if layer.line_height else []
        if len(lines) <= layer.max_lines and within(bounds, allowed) and not collisions:
            font_info = copy.deepcopy(layer.font_info)
            if font_info:
                effective = font_info["effective"]
                effective["font_size_output_pixels"] = size
                for metric in ("ascender", "descender", "line_gap"):
                    effective["metrics"][metric + "_pixels"] = effective["metrics"][metric] * size / effective["units_per_em"]
                font_info["runs"] = [{"line_index": i, "font_sha256": effective["sha256"], "derived_sha256": font_info["derived_sha256"],
                                      "font_face": effective["font_face"], "axes": effective["effective_axes"],
                                      "baseline": line[2]} for i, line in enumerate(positioned)]
            return LayerPlan(
                layer,
                tuple(positioned),
                bounds,
                size,
                digest,
                suffix_position=suffix_position,
                ornament_positions=tuple(ornament_positions),
                decoration_asset_sha256=decoration_digest,
                font_info=font_info,
                glyph_bounds=glyph_bounds,
                layout_info={"role": layer.role, "layer_id": layer.instance_id or layer.role, "constraint": "fit",
                             "preferred_font_size": preferred, "effective_font_size": size, "shrink_pixels": preferred - size,
                             "allowed": allowed, "glyph_bounds": glyph_bounds, "effect_bounds": bounds,
                             "line_count": len(lines), "anchor_mode": layer.anchor_mode, "scale": scale},
                typography={"word_spacing_em": layer.word_spacing, "word_spacing_pixels": size * layer.word_spacing,
                            "tracking_em": layer.tracking, "tracking_pixels": size * layer.tracking,
                            "baseline_step": step, "baselines": [v[2] for v in positioned],
                            "forced_breaks": layer.forced_breaks, "preferred_breaks": layer.preferred_breaks,
                            "backend": (font.primary if hasattr(font, "primary") else font).backend},
            )
    if layer.line_height and collisions:
        raise ReferenceError("line_height_collision", "Configured baseline step overlaps line ink/effect bounds", details={
            "path": "/layers/" + layer.role + "/line_height", "role": layer.role, "baseline_step": step,
            "line_pairs": collisions, "bounds": bounds, "allowed": allowed, "suggestions": ["increase_line_height", "reduce_effects"]})
    raise FitError(
        layer.role,
        last_bounds,
        allowed,
        minimum if layer.fit == "shrink" else preferred,
        last_count,
    )
