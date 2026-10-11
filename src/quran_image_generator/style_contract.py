"""Authoritative caption style constraints and public measurement semantics."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .diagnostics import pointer, validate_schema
from .references import ReferenceError

RANGES = {
    "font_size": (1, 256), "min_font_size": (1, 256), "max_lines": (1, 8),
    "opacity": (0, 1), "outline_width": (0, 8), "shadow_blur": (0, 16),
    "shadow_opacity": (0, 1), "suffix_scale": (0.25, 1), "line_spacing": (0, 64),
    "safe_margin": (0, 64), "suffix_spacing": (0, 32), "suffix_offset": (-32, 32),
    "quote_spacing": (0, 32), "horizontal_scale": (0.5, 2), "decoration_scale": (0.5, 2),
    "word_spacing": (0, 2), "line_height": (0, 4), "tracking": (0, 1),
    "font_face": (0, 31),
}
ENUMS = {
    "direction": ["rtl", "ltr"], "fit": ["wrap", "shrink"],
    "baseline_anchor": ["first", "last"], "alignment": ["left", "center", "right"],
    "numeral_system": ["latin", "arabic_indic"],
}
REFERENCE_FIELDS = {
    "font_size", "min_font_size", "outline_width", "shadow_offset", "shadow_blur",
    "line_spacing", "safe_margin", "suffix_spacing", "suffix_offset", "quote_spacing",
}
DESCRIPTIONS = {
    "anchor": "Normalized x and baseline y in canvas coordinates",
    "region": "Normalized allowed rectangle: left, top, right, bottom",
    "line_spacing": "Extra distance after the largest line ink height; legacy baseline rhythm",
    "suffix_scale": "True verse-end number size relative to fitted body size",
    "horizontal_scale": "Scale the complete shaped line horizontally",
    "decoration_scale": "Quotation font size relative to fitted body size",
    "sha256": "Optional required primary font or image byte identity",
    "enabled": "Explicitly disabled layers produce no asset",
    "required": "Missing content fails when enabled and required",
    "word_spacing": "Additional word gap in em of the final fitted font; zero preserves legacy spacing",
    "line_height": "Baseline step in fitted em; zero uses legacy line_spacing",
    "tracking": "Additional Latin grapheme gap in fitted em; optional cross-grapheme ligatures are disabled",
    "font_face": "Zero-based selected collection face; ordinary fonts have only face 0",
    "variation_axes": "JSON object of selected-font axis tags and values; other axes stay at font defaults",
    "font_features": "JSON array of OpenType feature tags; required Arabic shaping cannot be disabled",
    "font_language": "Explicit BCP-47 shaping language; requires Pillow-RAQM",
    "font_fallbacks": "Ordered JSON array of pinned local fonts with license/attribution; whole-layer fallback preserves joins and marks",
}


def field_metadata(name: str, spec: dict[str, Any], default: Any) -> dict[str, Any]:
    result = {**spec, "default": json.loads(json.dumps(default)),
              "description": DESCRIPTIONS.get(name, name.replace("_", " ").capitalize())}
    if name in RANGES:
        result.update(minimum=RANGES[name][0], maximum=RANGES[name][1])
    if name in ENUMS:
        result["enum"] = ENUMS[name]
    if name in ("anchor", "region"):
        result["items"] = {"type": "number", "minimum": 0, "maximum": 1}
    if name == "shadow_offset":
        result["items"] = {"type": "number", "minimum": -32, "maximum": 32}
    if name in ("quote_open", "quote_close", "marker_prefix", "marker_suffix"):
        result.update(maxLength=8, pattern=r"^\S*$")
    if name.endswith("color") or name == "color":
        result["x-format"] = "opaque_rgb; opacity is a separate field"
    result["x-units"] = ("em" if name in ("word_spacing", "line_height", "tracking") else "reference_pixels" if name in REFERENCE_FIELDS else
                         "normalized_canvas" if name in ("anchor", "region") else
                         "ratio" if name in ("opacity", "shadow_opacity", "suffix_scale", "horizontal_scale", "decoration_scale") else "unitless")
    result["x-scaling"] = "canvas_width/576" if name in REFERENCE_FIELDS else "none"
    result["x-roles"] = (["arabic"] if name.startswith(("quote_", "marker_", "suffix_", "decoration_")) or name == "numeral_system"
                         else ["arabic", "translation", "arabic_title", "latin_title", "logo"])
    result["x-applies-to"] = "layer" if name in ("enabled", "required", "opacity", "z_order", "anchor", "region", "sha256", "safe_margin") else "text"
    if name in ("min_font_size", "font_size"):
        result["x-constraints"] = ["min_font_size <= font_size after resolving omitted defaults"]
    if name == "region":
        result["x-constraints"] = ["left < right", "top < bottom"]
    if name in ("word_spacing", "tracking"):
        result["x-constraints"] = (["requires native Wand-RAQM for nonzero spacing"] if name == "word_spacing" else
                                  ["nonzero tracking supports LTR Latin graphemes only", "combining marks remain attached"])
    return result


def validate_layer_style(layer: Any, *, prefix: str | None = None, code: str = "invalid_request") -> None:
    from .contract_schema import style_schema

    path = prefix if prefix is not None else "/layers" + pointer([layer.role])
    schema = style_schema()
    value = {k: v for k, v in asdict(layer).items() if k in schema["properties"]}
    try:
        value = json.loads(json.dumps(value, allow_nan=False))
    except (ValueError, TypeError) as error:
        raise ReferenceError(code, "Style requires finite JSON values", details={"path": path}) from error
    try:
        validate_schema(value, schema, prefix=path, code=code)
    except ReferenceError as error:
        error.details["role"] = layer.role
        raise
    if layer.min_font_size > layer.font_size:
        raise ReferenceError(code, "Font size is below the resolved minimum", details={
            "path": path + "/font_size", "role": layer.role, "value": layer.font_size,
            "resolved_minimum": layer.min_font_size, "constraint": "min_font_size <= font_size"})
    if layer.region[0] >= layer.region[2] or layer.region[1] >= layer.region[3]:
        raise ReferenceError(code, "Region requires left < right and top < bottom", details={"path": path + "/region", "role": layer.role})
