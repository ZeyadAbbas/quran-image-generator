"""Explicit flow groups, coordinated fit and declared collision diagnostics."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from .anchoring import shift_plan
from .caption_fit import plan_text, within
from .contract_schema import GROUP
from .diagnostics import validate_schema
from .panels import (
    group_panel_plans,
    panel_geometry,
    panel_style,
    plan_panel_text,
    union,
)
from .references import ReferenceError
from .scenes import Layer, LayerPlan, Scene, checked_asset, dimension_scale, plan_scene


def overflow(bounds: tuple[int, int, int, int], allowed: tuple[int, int, int, int]) -> dict[str, int]:
    return {"left": max(0, allowed[0] - bounds[0]), "top": max(0, allowed[1] - bounds[1]),
            "right": max(0, bounds[2] - allowed[2]), "bottom": max(0, bounds[3] - allowed[3])}


def _region(scene: Scene, value: list[float]) -> tuple[int, int, int, int]:
    return tuple(round(v * (scene.width if i % 2 == 0 else scene.height)) for i, v in enumerate(value))  # type: ignore[return-value]


def _defaults(group: dict[str, Any]) -> dict[str, Any]:
    result = {name: spec["default"] for name, spec in GROUP["properties"].items() if "default" in spec}
    result.update(group)
    return result


def _flow(scene: Scene, group: dict[str, Any], members: list[Layer]) -> tuple[LayerPlan, ...]:
    active = [layer for layer in members if layer.enabled and (layer.text or layer.image)]
    if any(layer.image for layer in active):
        raise ReferenceError("unsupported_group_member", "Flow groups support text and font glyphs; PNG layers remain available in overlay groups", details={"group_id": group["group_id"]})
    inactive = [layer for layer in members if layer not in active]
    omitted = plan_scene(replace(scene, layers=tuple(inactive), groups=()))
    if not active:
        return omitted
    allowed = _region(scene, group["region"])
    if allowed[0] >= allowed[2] or allowed[1] >= allowed[3]:
        raise ReferenceError("invalid_group", "Group region needs ordered edges", details={"group_id": group["group_id"]})
    ratios = group.get("size_ratios", {})
    known = {layer.instance_id or layer.role for layer in members}
    if set(ratios) - known:
        raise ReferenceError("invalid_group", "Size ratios must name declared group children", details={"group_id": group["group_id"]})
    preferred = {layer.instance_id or layer.role: layer.font_size * ratios.get(layer.instance_id or layer.role, 1) for layer in active}
    minimum_factor = max(layer.min_font_size / preferred[layer.instance_id or layer.role] for layer in active)
    if minimum_factor > 1:
        raise ReferenceError("invalid_group", "Size ratio puts a child below its readable minimum", details={"group_id": group["group_id"], "constraint": "minimum_font_size"})
    maximum = max(preferred.values())
    attempts = min(256, math.ceil((1 - minimum_factor) * maximum))
    factors = [max(minimum_factor, 1 - n * (1 - minimum_factor) / max(1, attempts)) for n in range(attempts + 1)] if group["fit"] == "shrink" else [1.0]
    failure: dict[str, Any] = {}
    for factor in factors:
        first_size = preferred[active[0].instance_id or active[0].role] * factor * dimension_scale(scene, active[0])
        reference_scale = dimension_scale(scene, replace(active[0], scale_basis=group["scale_basis"]))
        unit = first_size if group["unit"] == "em" else reference_scale
        px, py = (v * unit for v in group["padding"])
        inner = (math.ceil(allowed[0] + px), math.ceil(allowed[1] + py), math.floor(allowed[2] - px), math.floor(allowed[3] - py))
        gap = group["gap"] * unit
        if inner[0] >= inner[2] or inner[1] >= inner[3]:
            failure = {"constraint": "group_padding", "allowed": allowed, "actual": inner}
            continue
        child_inner = inner
        if group.get("panel"):
            backplate = panel_style(group["panel"])
            if backplate["enabled"]:
                panel_unit = first_size if backplate["unit"] == "em" else reference_scale
                panel_pad = backplate["padding"][0] * panel_unit
                blur = 4 * backplate["shadow_blur"] * panel_unit if backplate["shadow_opacity"] else 0
                dx = backplate["shadow_offset"][0] * panel_unit if backplate["shadow_opacity"] else 0
                child_inner = (inner[0] + math.ceil(panel_pad + blur + max(0, -dx)), inner[1],
                               inner[2] - math.ceil(panel_pad + blur + max(0, dx)), inner[3])
        if child_inner[0] >= child_inner[2]:
            failure = {"constraint": "shared_panel_width", "allowed": inner}
            continue
        plans = []
        blocked = None
        for layer in active:
            identifier = layer.instance_id or layer.role
            temp = replace(layer, region=(child_inner[0] / scene.width, child_inner[1] / scene.height, child_inner[2] / scene.width, child_inner[3] / scene.height),
                           anchor=(0.5, 0.5), anchor_space="region", anchor_mode="block_middle", anchor_horizontal="center", fit="wrap")
            size = preferred[identifier] * factor * dimension_scale(scene, layer)
            size = max(1, round(size, 2) if factor != 1 or isinstance(layer.font_size, float) or identifier in ratios else round(size))
            try:
                digest = checked_asset(layer.font, layer.sha256)
                plan = plan_panel_text(scene, temp, digest, preferred_size=size) if temp.panel else plan_text(scene, temp, digest, preferred_size=size)
                if group["fit"] == "fail" and len(plan.lines) > max(1, len(layer.text.splitlines()) + len(layer.forced_breaks)):
                    blocked = {"layer_id": identifier, "role": layer.role, "constraint": "automatic_wrap_forbidden", "line_count": len(plan.lines)}
                    break
                plans.append(replace(plan, layer=layer))
            except ReferenceError as error:
                error.details = {**getattr(error, "details", {}), "layer_id": identifier}
                if error.code not in ("layout_overflow", "line_height_collision", "resource_limit"):
                    raise
                if error.code == "resource_limit" and getattr(error, "details", {}).get("field") not in ("font_size", "decoration_scale"):
                    raise
                blocked = {"layer_id": identifier, "role": layer.role, "constraint": error.code, "child_error": getattr(error, "details", {})}
                break
        if blocked:
            failure = blocked
            continue
        cursor = 0.0
        placed = []
        for plan in plans:
            assert plan.bounds is not None
            b = plan.bounds
            x = child_inner[0] if group["horizontal_alignment"] == "left" else child_inner[2] - (b[2] - b[0]) if group["horizontal_alignment"] == "right" else (child_inner[0] + child_inner[2] - b[2] + b[0]) / 2
            placed.append(shift_plan(plan, round(x - b[0]), round(cursor - b[1])))
            cursor += b[3] - b[1] + gap
        bounds = union([p.bounds for p in placed if p.bounds])
        if group.get("panel") and panel_style(group["panel"])["enabled"]:
            panel = panel_geometry(panel_style(group["panel"]), bounds, placed[0].font_size, reference_scale)
            bounds = union([bounds, panel["bounds"]])
        y = inner[1] if group["vertical_alignment"] == "top" else inner[3] - (bounds[3] - bounds[1]) if group["vertical_alignment"] == "bottom" else (inner[1] + inner[3] - bounds[3] + bounds[1]) / 2
        dy = round(y - bounds[1])
        final_bounds = (bounds[0], bounds[1] + dy, bounds[2], bounds[3] + dy)
        if not within(final_bounds, inner):
            failure = {"constraint": "group_envelope", "allowed": inner, "actual": final_bounds, "overflow": overflow(final_bounds, inner),
                       "layer_id": placed[-1].layer.instance_id or placed[-1].layer.role}
            continue
        result = []
        for plan in placed:
            shifted = shift_plan(plan, 0, dy)
            details = dict(shifted.layout_info or {})
            details.update(group_id=group["group_id"], mode="flow", group_bounds=final_bounds, group_region=allowed, group_factor=factor,
                           gap_pixels=gap, group_padding_pixels=(px, py), position_owner="caption_group",
                           effective_font_size=shifted.font_size, bounds=shifted.bounds, glyph_bounds=shifted.glyph_bounds,
                           baselines=[v[2] for v in shifted.lines])
            result.append(replace(shifted, layout_info=details))
        return (*result, *omitted)
    raise ReferenceError("group_fit_failed", "Caption group cannot fit within per-role readable minima", details={
        "group_id": group["group_id"], "path": "/caption_groups", "minimum_factor": minimum_factor, "attempted_factors": len(factors),
        "layer_id": active[0].instance_id or active[0].role,
        "preferred_sizes": preferred, "minimum_sizes": {layer.instance_id or layer.role: layer.min_font_size for layer in active},
        "suggestions": ["enlarge_group_region", "split_cue", "reduce_effects_or_padding"], **failure})


def plan_group_scene(scene: Scene) -> tuple[LayerPlan, ...]:
    by_id = {layer.instance_id or layer.role: layer for layer in scene.layers}
    groups = []
    seen: set[str] = set()
    claimed: set[str] = set()
    for index, source in enumerate(scene.groups):
        validate_schema(source, GROUP, prefix=f"/caption_groups/{index}")
        group = _defaults(source)
        if group["group_id"] in seen:
            raise ReferenceError("invalid_group", "Duplicate caption group ID")
        seen.add(group["group_id"])
        unknown = set(group["layers"]) - by_id.keys() - {"translation", "arabic_title", "latin_title", "logo"}
        if unknown:
            raise ReferenceError("invalid_group", "Unknown caption-group child", details={"group_id": group["group_id"], "unknown": sorted(unknown)})
        if group["mode"] == "flow":
            duplicate = set(group["layers"]) & claimed
            if duplicate:
                raise ReferenceError("invalid_group", "A layer cannot be positioned by two flow groups", details={"layers": sorted(duplicate)})
            claimed.update(group["layers"])
        groups.append(group)
    result = list(plan_scene(replace(scene, layers=tuple(layer for layer in scene.layers if (layer.instance_id or layer.role) not in claimed), groups=())))
    for group in groups:
        if group["mode"] == "flow":
            try:
                result.extend(_flow(scene, group, [by_id[name] for name in group["layers"] if name in by_id]))
            except ReferenceError as error:
                error.details = getattr(error, "details", {})
                error.details["path"] = f"/caption_groups/{groups.index(group)}"
                raise
    ordered = tuple(sorted(result, key=lambda p: p.layer.z_order))
    by_plan = {p.layer.instance_id or p.layer.role: p for p in ordered}
    for group in groups:
        if group["collision"] == "reject":
            active = [by_plan[name] for name in group["layers"] if name in by_plan and by_plan[name].status == "ready" and by_plan[name].bounds]
            for i, left in enumerate(active):
                for right in active[i + 1:]:
                    a, b = left.bounds, right.bounds
                    assert a and b
                    if max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3]):
                        raise ReferenceError("layer_collision", "Declared non-overlap group has intersecting effect/panel envelopes", details={
                            "group_id": group["group_id"], "layers": [left.layer.instance_id or left.layer.role, right.layer.instance_id or right.layer.role],
                            "bounds": [a, b], "constraint": "collision"})
    return group_panel_plans(scene, ordered)
