"""Published JSON Schema draft 2020-12 contract definitions."""

from __future__ import annotations

from dataclasses import fields
from typing import Any, get_type_hints

from .scenes import Layer


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
        ):
            continue
        default = field.default
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
        "metadata": {"type": "object"},
        "title_surah": {"type": "integer", "minimum": 1, "maximum": 114},
        "arabic_title": {"type": "string", "maxLength": 256},
        "latin_title": {"type": "string", "maxLength": 256},
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
                    "render_batch",
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
                    )
                },
                "additionalProperties": False,
            },
            "translation_dataset": BINDING_DATASET,
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
        },
        ("schema_version", "request_id", "operation"),
    ),
    "allOf": [
        {
            "if": {
                "properties": {
                    "operation": {"enum": ["validate", "layout", "render_batch"]}
                }
            },
            "then": {"required": ["source_corpus", "canvas", "cues"]},
        },
        {
            "if": {"properties": {"operation": {"const": "render_batch"}}},
            "then": {"required": ["output_directory"]},
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
            "preflight": {"type": "object"},
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
                        "font_sha256": HASH,
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
