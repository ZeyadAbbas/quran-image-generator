"""Published JSON Schema draft 2020-12 contract definitions."""

from __future__ import annotations

from dataclasses import MISSING, fields
from typing import Any, get_type_hints

from .scenes import Layer
from .style_contract import field_metadata


def obj(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


TEXT = {"type": "string", "minLength": 1, "maxLength": 128}
HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
SPAN = obj(
    {
        "surah": {"type": "integer", "minimum": 0, "maximum": 114},
        "ayah": {"type": "integer", "minimum": 0, "maximum": 286},
        "word_start": {"type": "integer", "minimum": 1},
        "word_end": {"type": "integer", "minimum": 1},
    },
    ("surah", "ayah", "word_start", "word_end"),
)
CORPUS = obj(
    {"edition": TEXT, "version": TEXT, "sha256": HASH}, ("edition", "version", "sha256")
)
ASSET = obj(
    {
        "path": {"type": "string", "minLength": 1, "maxLength": 4096},
        "sha256": HASH,
        "license": {"type": "string", "maxLength": 4096},
        "attribution": {"type": "string", "maxLength": 4096},
        "glyph": {"type": "string", "minLength": 1, "maxLength": 8},
    },
    ("path", "sha256", "license", "attribution"),
)
AXES = {"type": "object", "maxProperties": 16, "propertyNames": {"pattern": "^[A-Za-z0-9]{4}$"}, "additionalProperties": {"type": "number"}}
FONT_FALLBACK = obj({**{k: v for k, v in ASSET["properties"].items() if k != "glyph"},
                     "font_face": {"type": "integer", "minimum": 0, "maximum": 31}, "variation_axes": AXES},
                    ("path", "sha256", "license", "attribution"))
PANEL = obj({
    "enabled": {"type": "boolean", "default": True}, "mode": {"enum": ["block", "line", "region"], "default": "block"},
    "color": {"type": "string", "maxLength": 64, "default": "#000000"}, "opacity": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.6},
    "padding": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number", "minimum": 0, "maximum": 64}, "default": [0.5, 0.35]},
    "unit": {"enum": ["em", "reference_pixels"], "default": "em"},
    "corner_radius": {"type": "number", "minimum": 0, "maximum": 64, "default": 0.25},
    "border_width": {"type": "number", "minimum": 0, "maximum": 16, "default": 0},
    "border_color": {"type": "string", "maxLength": 64, "default": "#000000"},
    "shadow_offset": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number", "minimum": -32, "maximum": 32}, "default": [0, 0]},
    "shadow_blur": {"type": "number", "minimum": 0, "maximum": 16, "default": 0},
    "shadow_color": {"type": "string", "maxLength": 64, "default": "#000000"},
    "shadow_opacity": {"type": "number", "minimum": 0, "maximum": 1, "default": 0},
    "inset": {"enum": ["effects", "ink"], "default": "effects"},
    "region": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "number", "minimum": 0, "maximum": 1}},
})
GROUP_PANEL = obj({**PANEL["properties"], "mode": {"enum": ["block"], "default": "block"}})
GROUP = obj({"group_id": {"type": "string", "minLength": 1, "maxLength": 64}, "layers": {"type": "array", "items": TEXT, "minItems": 1, "maxItems": 16, "uniqueItems": True},
             "panel": GROUP_PANEL, "mode": {"enum": ["overlay", "flow"], "default": "overlay"},
             "region": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "number", "minimum": 0, "maximum": 1}, "default": [0.05, 0.05, 0.95, 0.95]},
             "gap": {"type": "number", "minimum": 0, "maximum": 64, "default": 0.6},
             "padding": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number", "minimum": 0, "maximum": 64}, "default": [0, 0]},
             "unit": {"enum": ["em", "reference_pixels"], "default": "em"},
             "scale_basis": {"enum": ["width", "short_side", "pixels"], "default": "width"},
             "vertical_alignment": {"enum": ["top", "middle", "bottom"], "default": "middle"},
             "horizontal_alignment": {"enum": ["left", "center", "right"], "default": "center"},
             "fit": {"enum": ["wrap", "shrink", "fail"], "default": "wrap"},
             "collision": {"enum": ["allow", "reject"], "default": "allow"},
             "size_ratios": {"type": "object", "maxProperties": 16, "additionalProperties": {"type": "number", "exclusiveMinimum": 0, "maximum": 8}}},
            ("group_id", "layers"))


def style_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {}
    types = get_type_hints(Layer)
    for field in fields(Layer):
        # Content comes only from references/bindings and explicit asset selectors.
        if field.name in (
            "role",
            "text",
            "font",
            "image",
            "persistent",
            "suffix",
            "decoration_font",
            "decoration_sha256",
            "ornaments",
            "inline_markers",
            "forced_breaks",
            "preferred_breaks",
            "resolved_font", "resolved_font_sha256", "font_info",
            "marker_specs", "element_fonts",
            "instance_id", "kind",
        ):
            continue
        factory = field.default_factory
        default = factory() if field.default is MISSING and callable(factory) else field.default
        if isinstance(default, bool):
            properties[field.name] = {"type": "boolean"}
        elif types[field.name] in (float, int | float):
            properties[field.name] = {"type": "number"}
        elif isinstance(default, int):
            properties[field.name] = {"type": "integer"}
        elif isinstance(default, float):
            properties[field.name] = {"type": "number"}
        elif isinstance(default, tuple):
            properties[field.name] = {
                "type": "array",
                "items": {"type": "number"},
                "minItems": len(default),
                "maxItems": len(default),
            }
        else:
            properties[field.name] = {"type": "string", "maxLength": 64}
        if field.name == "variation_axes":
            properties[field.name] = AXES
        elif field.name == "font_features":
            properties[field.name] = {"type": "array", "maxItems": 32, "uniqueItems": True, "items": {"type": "string", "pattern": "^[+-]?[A-Za-z0-9]{4}(=[0-9]{1,3})?$"}}
        elif field.name == "font_fallbacks":
            properties[field.name] = {"type": "array", "maxItems": 4, "items": FONT_FALLBACK}
        elif field.name == "font_language":
            properties[field.name] = {"type": "string", "maxLength": 32, "pattern": "^([A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*)?$"}
        elif field.name in ("quotation_style", "marker_style"):
            names = ("enabled", "color", "opacity", "outline_width", "outline_color", "shadow_offset", "shadow_blur", "shadow_color", "shadow_opacity",
                     "font_face", "variation_axes", "font_features", "font_language", "font_fallbacks", "direction")
            element = {name: {**properties[name], "x-default-source": "body"} for name in names}
            element["offset"] = {"type": "array", "items": {"type": "number", "minimum": -32, "maximum": 32}, "minItems": 2, "maxItems": 2,
                                 "default": [0, 0], "x-units": "reference_pixels", "x-scaling": "canvas_width/576"}
            properties[field.name] = obj(element)
        elif field.name == "panel":
            properties[field.name] = PANEL
        properties[field.name] = field_metadata(field.name, properties[field.name], default)
    return obj(properties)


PROFILE = obj(
    {
        "id": TEXT,
        "revision": TEXT,
        "approval": {"enum": ["approved", "needs_review"]},
        "styles": {
            "type": "object",
            "additionalProperties": style_schema(),
            "maxProperties": 16,
        },
        "provenance": {"type": "object"},
    },
    ("id", "revision", "approval", "styles", "provenance"),
)
TRANSLATION_SOURCE = obj(
    {
        **{
            name: {"type": "string", "minLength": 1, "maxLength": 4096}
            for name in (
                "provider",
                "resource",
                "version",
                "translator",
                "license",
                "attribution",
            )
        },
        "direction": {"enum": ["ltr", "rtl"]},
    },
    (
        "provider",
        "resource",
        "version",
        "translator",
        "license",
        "attribution",
        "direction",
    ),
)
BINDING = obj(
    {
        "binding_id": TEXT,
        "revision": TEXT,
        "spans": {"type": "array", "items": SPAN, "minItems": 1, "maxItems": 32},
        "arabic_sha256": HASH,
        "source_text": {"type": "string", "minLength": 1, "maxLength": 100000},
        "source_text_sha256": HASH,
        "source_identity_sha256": HASH,
        "segments": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "items": {"type": "string", "minLength": 1, "maxLength": 8000},
        },
        "review_status": {"enum": ["approved", "needs_review"]},
        "reviewer": {"type": "string", "maxLength": 512},
        "edited": {"type": "boolean"},
        "mapping_revision": TEXT,
    },
    (
        "binding_id",
        "revision",
        "spans",
        "arabic_sha256",
        "source_text",
        "source_text_sha256",
        "source_identity_sha256",
        "segments",
        "review_status",
        "reviewer",
        "edited",
        "mapping_revision",
    ),
)
BINDING_DATASET = obj(
    {
        "schema_version": {"const": 1},
        "source": TRANSLATION_SOURCE,
        "corpus": CORPUS,
        "bindings": {"type": "array", "maxItems": 10000, "items": BINDING},
    },
    ("schema_version", "source", "corpus", "bindings"),
)
CUE = obj(
    {
        "cue_id": TEXT,
        "spans": {"type": "array", "items": SPAN, "minItems": 1, "maxItems": 32},
        "translation_policy": {"enum": ["none", "review", "required"]},
        "translation_binding_id": TEXT,
        "preview_unreviewed_translation": {"type": "boolean"},
        "metadata": {"type": "object"},
        "title_surah": {"type": "integer", "minimum": 1, "maximum": 114},
        "arabic_title": {"type": "string", "maxLength": 256},
        "latin_title": {"type": "string", "maxLength": 256},
        "line_breaks": {"type": "array", "maxItems": 128, "items": obj({
            "span_occurrence": {"type": "integer", "minimum": 0, "maximum": 31},
            "source_word": {"type": "integer", "minimum": 1},
            "mode": {"enum": ["forced", "preferred"]}}, ("span_occurrence", "source_word", "mode"))},
    },
    ("cue_id", "spans"),
)
REQUEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/ZeyadAbbas/quran-image-generator/blob/main/src/quran_image_generator/assets/schemas/request-v1.json",
    **obj(
        {
            "schema_version": {"const": 1},
            "request_id": TEXT,
            "operation": {
                "enum": [
                    "capabilities",
                    "preflight",
                    "validate",
                    "layout",
                    "inspect",
                    "inspect_fonts",
                    "render_batch",
                    "translation_catalog",
                    "prepare_translations",
                ]
            },
            "source_corpus": CORPUS,
            "canvas": obj(
                {
                    "width": {"type": "integer", "minimum": 16, "maximum": 4096},
                    "height": {"type": "integer", "minimum": 16, "maximum": 4096},
                },
                ("width", "height"),
            ),
            "profile": PROFILE,
            "assets": {
                "type": "object",
                "properties": {
                    role: ASSET
                    for role in (
                        "arabic",
                        "translation",
                        "arabic_title",
                        "latin_title",
                        "logo",
                        "decorations",
                        "quotes", "markers",
                    )
                },
                "additionalProperties": False,
            },
            "translation_dataset": BINDING_DATASET,
            "translation_resource": TEXT,
            "translation_language": TEXT,
            "snapshot_directory": {"type": "string", "minLength": 1, "maxLength": 4096},
            "source_snapshot_sha256": HASH,
            "source_license": {"type": "string", "minLength": 1, "maxLength": 4096},
            "source_attribution": {"type": "string", "minLength": 1, "maxLength": 4096},
            "translation_snapshot": obj(
                {"directory": {"type": "string", "maxLength": 4096}, "sha256": HASH},
                ("directory", "sha256"),
            ),
            "cues": {"type": "array", "items": CUE, "minItems": 1, "maxItems": 1000},
            "titles": {"type": "boolean"},
            "quotations": {"type": "boolean"},
            "verse_numbers": {"type": "boolean"},
            "cropped": {"type": "boolean"},
            "asset_cache_directory": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4096,
            },
            "deadline_seconds": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": 3600,
            },
            "output_directory": {"type": "string", "minLength": 1, "maxLength": 4096},
            "error_mode": {"enum": ["all_or_nothing", "per_cue"]},
            "require_approved_profile": {"type": "boolean"},
            "metadata": {"type": "object"},
            "font_samples": {"type": "object", "maxProperties": 16, "additionalProperties": {"type": "string", "maxLength": 8000}},
            "caption_groups": {"type": "array", "maxItems": 8, "items": GROUP},
        },
        ("schema_version", "request_id", "operation"),
    ),
    "allOf": [
        {
            "if": {
                "properties": {
                    "operation": {"enum": ["validate", "layout", "inspect", "render_batch"]}
                }
            },
            "then": {"required": ["source_corpus", "canvas", "cues"]},
        },
        {
            "if": {"properties": {"operation": {"const": "render_batch"}}},
            "then": {"required": ["output_directory"]},
        },
        {"if": {"properties": {"operation": {"const": "inspect_fonts"}}}, "then": {"required": ["assets"]}},
        {
            "if": {"properties": {"operation": {"const": "prepare_translations"}}},
            "then": {"required": ["source_corpus", "cues", "translation_resource",
                                   "snapshot_directory", "source_license", "source_attribution"]},
        },
    ],
}

ERROR_SCHEMA = obj(
    {
        "code": TEXT,
        "message": {"type": "string"},
        "retryable": {"type": "boolean"},
        "details": {"type": "object"},
    },
    ("code", "message", "retryable"),
)
PIXEL_BOX = {
    "type": ["array", "null"],
    "items": {"type": "integer"},
    "minItems": 4,
    "maxItems": 4,
}
POINT = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}
RESOLVED_SPAN = obj(
    {
        "source": SPAN,
        "text": {"type": "string"},
        "target_verse": TEXT,
        "character_start": {"type": "integer", "minimum": 0},
        "character_end": {"type": "integer", "minimum": 0},
        "starts_ayah": {"type": "boolean"},
        "ends_ayah": {"type": "boolean"},
        "mapping_revision": TEXT,
        "target_sha256": HASH,
    },
    (
        "source",
        "text",
        "target_verse",
        "character_start",
        "character_end",
        "starts_ayah",
        "ends_ayah",
        "mapping_revision",
        "target_sha256",
    ),
)
LAYER_PROPERTIES = {
    **style_schema()["properties"],
    "role": TEXT,
    **{name: {"type": "string"} for name in ("text", "font", "image", "suffix")},
    "persistent": {"type": "boolean"},
    "decoration_font": {"type": "string"},
    "decoration_sha256": {"anyOf": [HASH, {"const": ""}]},
    "ornaments": {"type": "boolean"},
    "inline_markers": {"type": "array", "items": {"type": "string"}, "maxItems": 32},
    "forced_breaks": {"type": "array", "items": {"type": "integer"}, "maxItems": 128},
    "preferred_breaks": {"type": "array", "items": {"type": "integer"}, "maxItems": 128},
    "resolved_font": {"type": "string"}, "resolved_font_sha256": {"anyOf": [HASH, {"const": ""}]},
    "font_info": {"type": ["object", "null"]},
    "marker_specs": {"type": "array", "items": {"type": "object"}, "maxItems": 32},
    "element_fonts": {"type": "object"},
    "instance_id": {"type": "string", "maxLength": 128}, "kind": {"enum": ["text", "panel"]},
}
LAYER_PLAN = obj(
    {
        "layer": obj(
            LAYER_PROPERTIES,
            tuple(
                name
                for name in LAYER_PROPERTIES
                if name
                not in (
                    "quote_open",
                    "quote_close",
                    "numeral_system",
                    "marker_prefix",
                    "marker_suffix",
                    "suffix_spacing",
                    "suffix_offset",
                    "quote_spacing",
                    "decoration_font",
                    "decoration_sha256",
                    "ornaments",
                    "inline_markers",
                    "horizontal_scale",
                    "decoration_scale",
                    "word_spacing",
                    "line_height",
                    "tracking",
                    "forced_breaks",
                    "preferred_breaks",
                    "font_face", "variation_axes", "font_features", "font_language", "font_fallbacks",
                    "resolved_font", "resolved_font_sha256", "font_info",
                    "decoration_layout", "quotation_style", "marker_style", "quote_open_enabled", "quote_close_enabled", "marker_placement", "marker_specs", "element_fonts",
                    "panel", "instance_id", "kind",
                    "scale_basis", "anchor_mode", "anchor_space", "anchor_horizontal",
                )
            ),
        ),
        "lines": {
            "type": "array",
            "items": {
                "type": "array",
                "prefixItems": [
                    {"type": "string"},
                    {"type": "number"},
                    {"type": "number"},
                ],
                "minItems": 3,
                "maxItems": 3,
            },
        },
        "bounds": PIXEL_BOX,
        "font_size": {"type": "number", "minimum": 0},
        "asset_sha256": {"anyOf": [HASH, {"const": ""}]},
        "decoration_asset_sha256": {"anyOf": [HASH, {"const": ""}]},
        "status": {"enum": ["ready", "disabled", "omitted_optional"]},
        "suffix_position": {
            "type": ["array", "null"],
            "items": {"type": "number"},
            "minItems": 3,
            "maxItems": 3,
        },
        "ornament_positions": {
            "type": "array",
            "maxItems": 2,
            "items": {
                "type": "array",
                "prefixItems": [
                    {"type": "string"},
                    {"type": "number"},
                    {"type": "number"},
                ],
                "minItems": 3,
                "maxItems": 3,
            },
        },
        "typography": {"type": ["object", "null"]},
        "font_info": {"type": ["object", "null"]},
        "elements": {"type": "array", "items": {"type": "object"}, "maxItems": 128},
        "glyph_bounds": PIXEL_BOX,
        "panels": {"type": "array", "maxItems": 8, "items": {"type": "object"}},
        "asset_id": {"anyOf": [HASH, {"const": ""}]},
        "layout_info": {"type": ["object", "null"]},
    },
    (
        "layer",
        "lines",
        "bounds",
        "font_size",
        "asset_sha256",
        "status",
        "suffix_position",
    ),
)
RESPONSE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **obj(
        {
            "schema_version": {"const": 1},
            "renderer_version": TEXT,
            "request_id": {"type": ["string", "null"]},
            "status": {"enum": ["complete", "needs_review", "partial", "failed"]},
            "corpus": {"type": "object"},
            "profile": {"type": "object"},
            "runtime": {"type": "object"},
            "capabilities": {"type": "object"},
            "font_inspection": {"type": "object"},
            "preflight": {"type": "object"},
            "translation_catalog": {"type": "array", "items": {"type": "object"}},
            "translation_preparation": obj(
                {"dataset": BINDING_DATASET,
                 "source_snapshot": obj({"directory": {"type": "string"}, "sha256": HASH},
                                        ("directory", "sha256")),
                 "cues": {"type": "array", "items": obj(
                     {"cue_id": TEXT, "spans": {"type": "array", "items": SPAN},
                      "binding_id": {"type": ["string", "null"]},
                      "status": {"enum": ["bound", "needs_phrase_review"]}},
                     ("cue_id", "spans", "binding_id", "status"))}},
                ("dataset", "source_snapshot", "cues")),
            "cues": {
                "type": "array",
                "items": obj(
                    {
                        "cue_id": TEXT,
                        "status": {"enum": ["ready", "needs_review", "failed"]},
                        "arabic": {"type": "string"},
                        "source_spans": {"type": "array", "items": RESOLVED_SPAN},
                        "translation": {
                            "anyOf": [
                                {"type": "null"},
                                obj(
                                    {"source": TRANSLATION_SOURCE, "binding": BINDING},
                                    ("source", "binding"),
                                ),
                            ]
                        },
                        "metadata": {"type": "object"},
                        "layers": {"type": "array", "items": LAYER_PLAN},
                        "inspection": {"type": "object"},
                        "asset_ids": {"type": "array", "items": HASH},
                        "warnings": {"type": "array", "items": {"type": "string"}},
                        "error": ERROR_SCHEMA,
                    },
                    ("cue_id", "status", "metadata", "warnings", "asset_ids"),
                ),
            },
            "assets": {
                "type": "array",
                "items": obj(
                    {
                        "asset_id": HASH,
                        "path": {"type": "string"},
                        "sha256": HASH,
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                        "offset": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "bounds": PIXEL_BOX,
                        "alpha_mode": {"const": "straight"},
                        "color_space": {"const": "sRGB"},
                        "roles": {"type": "array", "items": {"type": "string"}},
                        "persistent": {"type": "boolean"},
                        "effect_bounds": PIXEL_BOX,
                        "anchor": POINT,
                        "font_sha256": {"anyOf": [HASH, {"const": ""}]},
                    },
                    (
                        "asset_id",
                        "path",
                        "sha256",
                        "width",
                        "height",
                        "offset",
                        "bounds",
                        "alpha_mode",
                        "color_space",
                        "roles",
                        "persistent",
                        "effect_bounds",
                        "anchor",
                        "font_sha256",
                    ),
                ),
            },
            "job_directory": {"type": "string"},
            "metadata": {"type": "object"},
            "error": ERROR_SCHEMA,
        },
        (
            "schema_version",
            "renderer_version",
            "request_id",
            "status",
            "cues",
            "assets",
        ),
    ),
}
