"""Pixel-stable ink/effect anchors and complete-plan translations."""

from __future__ import annotations

import copy
from dataclasses import replace

from .scenes import Layer, LayerPlan, Scene


def move_box(box: tuple[int, int, int, int] | None, dx: int, dy: int) -> tuple[int, int, int, int] | None:
    return (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy) if box else None


def anchor_offset(scene: Scene, layer: Layer, ink: tuple[int, int, int, int], bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    if layer.anchor_mode == "baseline":
        return 0, 0
    target = (layer.anchor[0] * scene.width, layer.anchor[1] * scene.height)
    if layer.anchor_space == "region":
        left, top, right, bottom = layer.region
        target = ((left + (right - left) * layer.anchor[0]) * scene.width,
                  (top + (bottom - top) * layer.anchor[1]) * scene.height)
    box = ink if layer.anchor_mode.startswith("ink_") else bounds
    vertical = layer.anchor_mode.split("_", 1)[1]
    y = box[1] if vertical == "top" else box[3] if vertical == "bottom" else (box[1] + box[3]) / 2
    horizontal = layer.anchor_horizontal
    right_edge = horizontal == "start" and layer.direction == "rtl" or horizontal == "end" and layer.direction == "ltr"
    x = (box[0] + box[2]) / 2 if horizontal == "center" else box[2] if right_edge else box[0]
    return round(target[0] - x), round(target[1] - y)


def shift_plan(plan: LayerPlan, dx: int, dy: int) -> LayerPlan:
    elements = []
    for element in plan.elements:
        item = dict(element)
        item.update(x=item["x"] + dx, y=item["y"] + dy,
                    bounds=move_box(item["bounds"], dx, dy), glyph_bounds=move_box(item["glyph_bounds"], dx, dy))
        elements.append(item)
    panels = tuple({**panel, "rect": move_box(panel["rect"], dx, dy), "bounds": move_box(panel["bounds"], dx, dy)} for panel in plan.panels)
    typography = copy.deepcopy(plan.typography)
    if typography and "baselines" in typography:
        typography["baselines"] = [v + dy for v in typography["baselines"]]
    info = copy.deepcopy(plan.font_info)
    if info:
        for run in info.get("runs", []):
            run["baseline"] += dy
    layout = copy.deepcopy(plan.layout_info)
    if layout:
        for name in ("bounds", "glyph_bounds", "effect_bounds", "block_bounds"):
            if layout.get(name):
                layout[name] = move_box(layout[name], dx, dy)
        if "baselines" in layout:
            layout["baselines"] = [v + dy for v in layout["baselines"]]
    return replace(plan, lines=tuple((text, x + dx, y + dy) for text, x, y in plan.lines),
                   bounds=move_box(plan.bounds, dx, dy), glyph_bounds=move_box(plan.glyph_bounds, dx, dy),
                   suffix_position=(plan.suffix_position[0] + dx, plan.suffix_position[1] + dy, plan.suffix_position[2]) if plan.suffix_position else None,
                   ornament_positions=tuple((text, x + dx, y + dy) for text, x, y in plan.ornament_positions),
                   elements=tuple(elements), panels=panels, typography=typography, font_info=info, layout_info=layout)
