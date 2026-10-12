"""Static, independent-alpha caption panels and source-bound shared backplates."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFilter

from .caption_fit import FitError, pixel_region, plan_text, within
from .contract_schema import GROUP, PANEL
from .diagnostics import validate_schema
from .references import ReferenceError
from .scenes import Layer, LayerPlan, Scene, _color_mask, dimension_scale, layer_font


def panel_style(value: dict[str, Any]) -> dict[str, Any]:
    validate_schema(value, PANEL, prefix="/panel")
    result = {k: v["default"] for k, v in PANEL["properties"].items() if "default" in v}
    result.update(value)
    for name in ("color", "border_color", "shadow_color"):
        try:
            if len(ImageColor.getrgb(result[name])) != 3:
                raise ValueError("opaque RGB required")
        except ValueError as error:
            raise ReferenceError("invalid_request", "Panel colors require opaque RGB and separate alpha", details={"path": "/panel/" + name}) from error
    return result


def union(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def line_bounds(scene: Scene, plan: LayerPlan, effects: bool = True) -> list[tuple[int, int, int, int]]:
    from .decoration_elements import _effect_box

    if plan.elements:
        return [union([v["bounds" if effects else "glyph_bounds"] for v in plan.elements if v["line_index"] == index]) for index in range(len(plan.lines))]
    layer = plan.layer
    font = layer_font(layer, plan.font_size)
    boxes = []
    scale = dimension_scale(scene, layer)
    style = {"outline_width": layer.outline_width, "shadow_offset": layer.shadow_offset, "shadow_blur": layer.shadow_blur, "shadow_opacity": layer.shadow_opacity}
    for text, x, y in plan.lines:
        box = font.getbbox(text)
        ink = (x + box[0], y + box[1], x + box[2], y + box[3])
        b = _effect_box(ink, style, scale) if effects else ink
        boxes.append((math.floor(b[0]), math.floor(b[1]), math.ceil(b[2]), math.ceil(b[3])))
    extra: list[tuple[int, str, float, float, float, Layer]] = []
    if plan.suffix_position:
        x, y, suffix_size = plan.suffix_position
        selected = replace(layer, font=layer.decoration_font, resolved_font="", resolved_font_sha256="", variation_axes={}, font_face=0, font_fallbacks=(), font_features=(), font_language="", inline_markers=(), horizontal_scale=1) if layer.decoration_font else layer
        extra.append((len(boxes) - 1, layer.suffix, x, y, suffix_size, selected))
    for index, (text, x, y) in enumerate(plan.ornament_positions):
        selected = replace(layer, font=layer.decoration_font, resolved_font="", resolved_font_sha256="", variation_axes={}, font_face=0, font_fallbacks=(), font_features=(), font_language="", inline_markers=(), horizontal_scale=1)
        extra.append((0 if index == 0 else len(boxes) - 1, text, x, y, plan.font_size * layer.decoration_scale, selected))
    for index, text, x, y, size, selected in extra:
        b = layer_font(selected, size).getbbox(text)
        ink = (x + b[0], y + b[1], x + b[2], y + b[3])
        b = _effect_box(ink, style, scale) if effects else ink
        boxes[index] = union([boxes[index], (math.floor(b[0]), math.floor(b[1]), math.ceil(b[2]), math.ceil(b[3]))])
    return boxes


def panel_geometry(style: dict[str, Any], box: tuple[int, int, int, int], font_size: float, scale: float, *, padded: bool = True) -> dict[str, Any]:
    factor = font_size if style["unit"] == "em" else scale
    px, py = (v * factor for v in style["padding"])
    rect = (math.floor(box[0] - (px if padded else 0)), math.floor(box[1] - (py if padded else 0)),
            math.ceil(box[2] + (px if padded else 0)), math.ceil(box[3] + (py if padded else 0)))
    radius = min(style["corner_radius"] * factor, (rect[2] - rect[0]) / 2, (rect[3] - rect[1]) / 2)
    blur = style["shadow_blur"] * factor
    dx, dy = (v * factor for v in style["shadow_offset"])
    extent = math.ceil(4 * blur) if style["shadow_opacity"] else 0
    bounds = (math.floor(rect[0] - extent + min(0, dx) if style["shadow_opacity"] else rect[0]),
              math.floor(rect[1] - extent + min(0, dy) if style["shadow_opacity"] else rect[1]),
              math.ceil(rect[2] + extent + max(0, dx) if style["shadow_opacity"] else rect[2]),
              math.ceil(rect[3] + extent + max(0, dy) if style["shadow_opacity"] else rect[3]))
    return {"rect": rect, "bounds": bounds, "radius": radius, "border_width": round(style["border_width"] * factor),
            "padding_pixels": (px, py), "shadow_offset": (dx, dy), "shadow_blur": blur, "style": style}


def add_panel(scene: Scene, plan: LayerPlan) -> LayerPlan:
    layer = plan.layer
    if plan.status != "ready" or not layer.panel:
        return plan
    style = panel_style(layer.panel)
    if not style["enabled"]:
        return plan
    if layer.image:
        raise ReferenceError("invalid_request", "Caption panels require text content", details={"path": "/profile/styles/" + layer.role + "/panel"})
    assert plan.bounds is not None
    boxes = line_bounds(scene, plan, effects=style["inset"] == "effects")
    if style["mode"] == "region":
        region = style.get("region", layer.region)
        if region[0] >= region[2] or region[1] >= region[3]:
            raise ReferenceError("invalid_request", "Panel region requires ordered edges", details={"path": "/panel/region"})
        box = tuple(round(v * (scene.width if i % 2 == 0 else scene.height)) for i, v in enumerate(region))
        geometry = panel_geometry(style, box, plan.font_size, dimension_scale(scene, layer), padded=False)
        px, py = geometry["padding_pixels"]
        inset = (math.ceil(box[0] + px), math.ceil(box[1] + py), math.floor(box[2] - px), math.floor(box[3] - py))
        if not within(union(boxes), inset):
            raise FitError(layer.role, union(boxes), inset, plan.font_size, len(plan.lines))
        panels = [geometry]
    else:
        panels = [panel_geometry(style, box, plan.font_size, dimension_scale(scene, layer)) for box in (boxes if style["mode"] == "line" else [union(boxes)])]
    bounds = union([plan.bounds, *[v["bounds"] for v in panels]])
    candidate = replace(plan, bounds=bounds, panels=tuple(panels))
    if layer.anchor_mode != "baseline" and candidate.glyph_bounds:
        from .anchoring import anchor_offset, shift_plan

        ax, ay = anchor_offset(scene, layer, candidate.glyph_bounds, bounds)
        candidate = shift_plan(candidate, ax, ay)
        assert candidate.bounds is not None
        bounds = candidate.bounds
    if not within(bounds, pixel_region(scene, layer)):
        error = FitError(layer.role, bounds, pixel_region(scene, layer), plan.font_size, len(plan.lines))
        error.details.update(constraint="panel_envelope", path="/profile/styles/" + layer.role + "/panel")
        raise error
    layout = dict(candidate.layout_info or {})
    layout.update(block_bounds=bounds, panel_bounds=union([v["bounds"] for v in candidate.panels]))
    return replace(candidate, layout_info=layout)


def plan_panel_text(scene: Scene, layer: Layer, digest: str, *, preferred_size: float | None = None) -> LayerPlan:
    if not panel_style(layer.panel)["enabled"]:
        return plan_text(scene, layer, digest, preferred_size=preferred_size)
    scale = dimension_scale(scene, layer)
    preferred = max(1, round(layer.font_size * scale, 2) if isinstance(layer.font_size, float) else round(layer.font_size * scale))
    minimum = max(1, round(layer.min_font_size * scale))
    if preferred_size is not None:
        preferred = preferred_size
    sizes = [max(minimum, preferred - n) for n in range(math.ceil(preferred - minimum) + 1)] if layer.fit == "shrink" else [preferred]
    for size in sizes:
        candidate = replace(layer, fit="wrap") if layer.fit == "shrink" else layer
        try:
            plan = add_panel(scene, plan_text(scene, candidate, digest, preferred_size=size))
            return replace(plan, layer=layer)
        except FitError as error:
            failure = error
        except ReferenceError as error:
            error.details = getattr(error, "details", {})
            error.details["role"] = layer.role
            if error.details.get("path", "").startswith("/panel"):
                error.details["path"] = "/profile/styles/" + layer.role + error.details["path"]
            raise
    raise failure


def group_panel_plans(scene: Scene, plans: tuple[LayerPlan, ...]) -> tuple[LayerPlan, ...]:
    by_id = {p.layer.instance_id or p.layer.role: p for p in plans}
    result = list(plans)
    ids = set()
    for index, group in enumerate(scene.groups):
        validate_schema(group, GROUP, prefix=f"/caption_groups/{index}")
        optional_roles = {"arabic", "translation", "arabic_title", "latin_title", "logo"}
        invalid = [name for name in group["layers"] if name not in by_id and (name not in optional_roles or any(p.layer.role == name for p in plans))]
        if group["group_id"] in ids or invalid:
            raise ReferenceError("invalid_group", "Groups need unique IDs and existing layer instances", details={"group_id": group["group_id"]})
        ids.add(group["group_id"])
        active = [by_id[name] for name in group["layers"] if name in by_id and by_id[name].status == "ready" and by_id[name].bounds]
        if not active or not group.get("panel"):
            continue
        try:
            style = panel_style(group["panel"])
        except ReferenceError as error:
            error.details = getattr(error, "details", {})
            error.details["path"] = f"/caption_groups/{index}" + error.details.get("path", "/panel")
            raise
        if not style["enabled"]:
            continue
        if style["mode"] != "block":
            raise ReferenceError("invalid_group", "Shared backplates use block mode", details={"group_id": group["group_id"], "path": f"/caption_groups/{index}/panel/mode"})
        em_size = next((p.font_size for p in active if p.font_size), 30 * scene.width / 576)
        reference_scale = dimension_scale(scene, replace(active[0].layer, scale_basis=group.get("scale_basis", "width")))
        geometry = panel_geometry(style, union([p.bounds for p in active if p.bounds]), em_size, reference_scale)
        if not within(geometry["bounds"], (0, 0, scene.width, scene.height)):
            raise FitError("panel", geometry["bounds"], (0, 0, scene.width, scene.height), 0, 0)
        layer = Layer("panel", required=False, kind="panel", instance_id="group-panel:" + group["group_id"], panel=style,
                      z_order=min(p.layer.z_order for p in active) - 1)
        result.append(LayerPlan(layer, (), geometry["bounds"], 0, "", panels=(geometry,)))
    if len(result) > 16:
        raise ReferenceError("resource_limit", "Panels and text together exceed 16 output layers")
    return tuple(sorted(result, key=lambda p: p.layer.z_order))


def paint_panels(plan: LayerPlan, image: Image.Image) -> None:
    for panel in plan.panels:
        left, top, right, bottom = panel["rect"]
        box = (left, top, right - 1, bottom - 1)
        style = panel["style"]
        with Image.new("L", image.size) as mask:
            ImageDraw.Draw(mask).rounded_rectangle(box, radius=panel["radius"], fill=255)
            if style["shadow_opacity"]:
                with mask.filter(ImageFilter.GaussianBlur(panel["shadow_blur"])) as blur, Image.new("L", image.size) as moved:
                    moved.paste(blur, tuple(round(v) for v in panel["shadow_offset"]))
                    _color_mask(image, moved, style["shadow_color"], style["shadow_opacity"])
            _color_mask(image, mask, style["color"], style["opacity"])
        if panel["border_width"]:
            with Image.new("L", image.size) as border:
                ImageDraw.Draw(border).rounded_rectangle(box, radius=panel["radius"], outline=255, width=panel["border_width"])
                _color_mask(image, border, style["border_color"], style["opacity"])
