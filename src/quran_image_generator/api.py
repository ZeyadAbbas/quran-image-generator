"""Version 1 public static-caption contract. No recognition, timing or publishing."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from functools import partial
from pathlib import Path
from typing import Any

import fontTools
import jsonschema
import PIL
from PIL import features

from .batching import AssetCache, BatchControl, BatchProgress
from .bindings import BindingDataset
from .content import TANZIL_TEXT_SHA256
from .contract_schema import REQUEST_SCHEMA, RESPONSE_SCHEMA, style_schema
from .diagnostics import validate_schema
from .excerpts import ExcerptRequest, select_excerpt
from .font_controls import FontWorkspace, inspect_font
from .profiles import CaptionProfile, decorate_excerpt
from .references import (
    BRIDGE_SHA256,
    MAPPING_REVISION,
    CorpusIdentity,
    ReferenceError,
    SourceSpan,
)
from .render_cache import CaptionRenderCache
from .scenes import (
    LayerPlan,
    Scene,
    caption_scene,
    checked_asset,
    plan_scene,
    render_layer,
)
from .snapshots import SnapshotStore, canonical_bytes
from .translation_tracks import (
    PreparedTrack,
    check_instance_collisions,
    enforce_instance_layout,
    prepare_tracks,
    resolve_annotations,
    resolve_tracks,
    validate_instances,
)
from .word_emphasis import PreparedWords, prepare_words, render_word_states
from .word_emphasis import descriptor as word_descriptor

SCHEMA_VERSION = 1
RENDERER_VERSION = "0.5.0"
MAX_REQUEST_BYTES = 8_000_000


@dataclass(frozen=True, slots=True)
class RenderRequest:
    """Typed validated request; JSON schema is shared by Python and CLI callers."""

    payload: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RenderRequest:
        if not isinstance(value, dict):
            raise ReferenceError("invalid_request", "Request must be an object")
        value = json.loads(canonical_bytes(value))
        if (
            value.get("schema_version") != SCHEMA_VERSION
            or type(value.get("schema_version")) is not int
        ):
            raise ReferenceError("unsupported_version", "Supported schema version is 1")
        if len(canonical_bytes(value)) > MAX_REQUEST_BYTES:
            raise ReferenceError("invalid_request", "Request exceeds 8 MB")
        validate_schema(value, REQUEST_SCHEMA)
        value.setdefault("render_backend", "pillow")
        if "cues" in value and len({cue["cue_id"] for cue in value["cues"]}) != len(
            value["cues"]
        ):
            raise ReferenceError(
                "duplicate_cue_id", "Cue IDs must be unique across occurrences"
            )
        if "translation_dataset" in value and "translation_snapshot" in value:
            raise ReferenceError(
                "invalid_request", "Choose one translation dataset or pinned snapshot"
            )
        validate_instances(value)
        if any(
            "glyph" in asset and role != "logo"
            for role, asset in value.get("assets", {}).items()
        ):
            raise ReferenceError(
                "invalid_request", "Only branding assets accept explicit symbol glyphs"
            )
        return cls(json.loads(canonical_bytes(value)))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(canonical_bytes(self.payload))
        return result


@dataclass(frozen=True, slots=True)
class RenderResponse:
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(canonical_bytes(self.payload))
        jsonschema.Draft202012Validator(RESPONSE_SCHEMA).validate(result)
        return result


def runtime_identity() -> dict[str, Any]:
    from .backends import FRIBIDI_SHA256

    native = "unavailable"
    native_raqm = False
    try:
        from wand.version import MAGICK_VERSION, MAGICK_VERSION_DELEGATES

        native = MAGICK_VERSION
        native_raqm = "raqm" in MAGICK_VERSION_DELEGATES.split()
    except (ImportError, OSError):
        pass
    return {
        "pillow": PIL.__version__,
        "pillow_raqm": features.check_feature("raqm"),
        "imagemagick": native,
        "native_raqm": native_raqm,
        "fonttools": fontTools.__version__,
        "pillow_freetype": features.version_module("freetype2"),
        "pillow_raqm_version": features.version_feature("raqm")
        if features.check_feature("raqm")
        else None,
        "pillow_harfbuzz": features.version_feature("harfbuzz")
        if features.check_feature("harfbuzz")
        else None,
        "pillow_fribidi": features.version_feature("fribidi")
        if features.check_feature("fribidi")
        else None,
        "pillow_fribidi_sha256": FRIBIDI_SHA256,
    }


def capabilities(backend: str = "pillow") -> dict[str, Any]:
    return {
        "schema_versions": [1],
        "operations": [
            "capabilities",
            "preflight",
            "validate",
            "layout",
            "inspect",
            "inspect_fonts",
            "render_batch",
            "translation_catalog",
            "prepare_translations",
        ],
        "renderer_version": RENDERER_VERSION,
        "render_backends": ["pillow", "imagemagick"],
        "default_render_backend": "pillow",
        "selected_render_backend": backend,
        "mapping_revision": MAPPING_REVISION,
        "mapping_sha256": BRIDGE_SHA256,
        "source_corpus": asdict(CorpusIdentity()),
        "target_corpus": {
            "edition": "Tanzil Uthmani Hafs",
            "version": "1.1",
            "sha256": TANZIL_TEXT_SHA256,
        },
        "profiles": [{"id": "plain", "revision": "1", "approval": "approved"}],
        "custom_profiles": True,
        "layer_roles": [
            "arabic",
            "translation",
            "arabic_title",
            "latin_title",
            "logo",
            "panel",
            "source_reference",
            "edition_label",
            "annotation",
        ],
        "style_fields": sorted(style_schema()["properties"]),
        "style_contract": style_descriptor(backend),
        "features": {
            "transparent_layers": True,
            "independent_titles_and_branding": True,
            "font_glyph_branding": True,
            "separate_decoration_font": True,
            "fractional_font_sizes": True,
            "whole_line_horizontal_scale": True,
            "word_spacing": runtime_identity()[
                "pillow_raqm" if backend == "pillow" else "native_raqm"
            ],
            "fixed_line_height": True,
            "latin_grapheme_tracking": True,
            "source_line_breaks": True,
            "font_inspection": True,
            "font_collection_faces": True,
            "variation_axes": True,
            "font_features": backend == "pillow" and runtime_identity()["pillow_raqm"],
            "font_language": backend == "pillow" and runtime_identity()["pillow_raqm"],
            "pinned_font_fallbacks": True,
            "independent_decoration_elements": True,
            "caption_panels": True,
            "shared_group_backplates": True,
            "gradient_panels": False,
            "ink_and_block_anchors": True,
            "caption_group_flow": True,
            "coordinated_group_fit": True,
            "declared_collision_checks": True,
            "dimension_scale_basis": True,
            "outline_and_shadow": True,
            "reviewed_phrase_bindings": True,
            "offline_translation_snapshots": True,
            "translation_source_preparation": True,
            "unreviewed_translation_preview": True,
            "independent_translation_tracks": True,
            "verified_source_labels": True,
            "approved_presentation_annotations": True,
        },
        "limits": {
            "request_bytes": MAX_REQUEST_BYTES,
            "cues": 1000,
            "spans_per_cue": 32,
            "layers": 16,
            "canvas_pixels": 8_500_000,
            "tracked_graphemes_per_line": 512,
            "group_fit_attempts": 257,
            "translation_tracks": 8,
            "annotations": 4,
            "annotation_characters": 512,
        },
        "alpha_mode": "straight",
        "color_space": "sRGB",
        "word_highlighting": backend == "pillow" and runtime_identity()["pillow_raqm"],
        "word_emphasis": word_descriptor(backend, runtime_identity()["pillow_raqm"]),
        "runtime": runtime_identity(),
    }


def style_descriptor(backend: str = "pillow") -> dict[str, Any]:
    """Versioned defaults, constraints and units suitable for generated controls."""
    from .caption_editor import LAYER_ROLES, default_styles

    runtime = runtime_identity()
    active = (
        ("pillow_raqm" if runtime["pillow_raqm"] else "unavailable")
        if backend == "pillow"
        else ("wand_raqm" if runtime["native_raqm"] else "unavailable")
    )
    fields = copy.deepcopy(style_schema()["properties"])
    for spec in fields.values():
        spec["backend_support"] = {"pillow_raqm": True, "wand_raqm": True}
    for name in ("font_features", "font_language"):
        fields[name]["backend_support"] = {"pillow_raqm": True, "wand_raqm": False}
    return {
        "word_emphasis": word_descriptor(backend, runtime["pillow_raqm"]),
        "descriptor_version": 1,
        "schema_version": 1,
        "fields": fields,
        "role_defaults": {role: default_styles(role) for role in LAYER_ROLES},
        "instance_defaults": {
            "translation": {
                **default_styles("translation"),
                "anchor": [0.5, 0.5],
                "region": [0.05, 0.05, 0.95, 0.95],
            },
            "annotation": {
                **default_styles("translation"),
                "font_size": 12,
                "z_order": 10,
                "anchor": [0.5, 0.5],
                "region": [0.05, 0.05, 0.95, 0.95],
            },
        },
        "instance_index_adjusted_defaults": ["z_order"],
        "request_schema": REQUEST_SCHEMA,
        "request_defaults": {
            "render_backend": "pillow",
            "titles": False,
            "quotations": False,
            "verse_numbers": False,
            "cropped": False,
            "error_mode": "all_or_nothing",
            "require_approved_profile": False,
            "deadline_seconds": 300,
        },
        "asset_roles": [*LAYER_ROLES, "decorations", "quotes", "markers"],
        "element_layout": {
            "directions": ["rtl"],
            "representation": "combined_rgba_with_element_geometry",
        },
        "backend": {
            "active": active,
            "shaping": active != "unavailable",
            "font_features": backend == "pillow" and runtime["pillow_raqm"],
            "font_language": backend == "pillow" and runtime["pillow_raqm"],
            "variation_axes": True,
            "font_fallbacks": True,
            "fallback_policy": "whole_layer",
            "word_spacing": runtime[
                "pillow_raqm" if backend == "pillow" else "native_raqm"
            ],
            "tracking_scripts": ["Latin LTR"],
        },
        "constraints": [
            "min_font_size <= font_size",
            "region left < right; top < bottom",
            "opaque RGB colors with separate alpha",
            "effective font size <= 512 output pixels",
            "custom profiles require provenance",
            "unavailable fields fail; no settings are discarded",
        ],
    }


def inspect_request(request: RenderRequest | dict[str, Any], *, asset_root: Path | None = None) -> RenderResponse:
    """Resolve styles and layout using the same renderer, without producing files."""
    data = request.to_dict() if isinstance(request, RenderRequest) else copy.deepcopy(request)
    data["operation"] = "inspect"
    return execute_request(data, asset_root=asset_root)


def common_size_suggestion(response: RenderResponse | dict[str, Any]) -> dict[str, Any]:
    """Suggest reference sizes from layout batches; callers replay to validate."""
    data = response.to_dict() if isinstance(response, RenderResponse) else response
    sizes: dict[str, float] = {}
    failed = []
    for cue in data["cues"]:
        if cue["status"] == "failed":
            failed.append(cue["cue_id"])
            continue
        for plan in cue.get("layers", []):
            if plan["status"] != "ready" or not plan["font_size"]:
                continue
            scale = (plan.get("layout_info") or {}).get("scale", 1)
            key = plan["layer"].get("instance_id") or plan["layer"]["role"]
            size = plan["font_size"] / scale
            sizes[key] = min(sizes.get(key, size), size)
    return {"reference_sizes": sizes, "failed_cues": failed, "requires_revalidation": True}


def error_record(error: ReferenceError) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": error.code,
        "message": str(error),
        "retryable": error.code in ("output_io", "translation_deadline", "translation_unavailable"),
    }
    if hasattr(error, "details"):
        result["details"] = error.details
    return result


def failure_response(request_id: str | None, error: ReferenceError) -> RenderResponse:
    return RenderResponse(
        {
            "schema_version": 1,
            "renderer_version": RENDERER_VERSION,
            "request_id": request_id,
            "status": "failed",
            "cues": [],
            "assets": [],
            "error": error_record(error),
        }
    )


def _local_path(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _prepare_cue(
    data: dict[str, Any],
    cue: dict[str, Any],
    root: Path,
    dataset: BindingDataset | None,
    font_workspace: FontWorkspace,
    tracks: tuple[PreparedTrack, ...] = (),
    cache: CaptionRenderCache | None = None,
) -> tuple[dict[str, Any], Scene, tuple[LayerPlan, ...]]:
    spans = tuple(SourceSpan(**span) for span in cue["spans"])
    policy = cue.get("translation_policy", "none")
    excerpt = select_excerpt(
        ExcerptRequest(
            cue["cue_id"],
            spans,
            CorpusIdentity(**data["source_corpus"]),
            policy,
            cue.get("translation_binding_id"),
        )
    )
    translation = None
    english = ""
    warnings = []
    if policy != "none":
        if dataset is None or not cue.get("translation_binding_id"):
            if policy == "required":
                raise ReferenceError(
                    "missing_translation",
                    "Required phrase translation dataset/binding is missing",
                )
            warnings.append(
                "translation_review_required; Arabic-only preview explicitly selected"
            )
        else:
            binding = dataset.lookup(
                cue["translation_binding_id"],
                spans,
                require_approved=policy == "required",
            )
            translation = {"source": asdict(dataset.source), "binding": asdict(binding)}
            if binding.review_status == "approved":
                english = binding.text
            elif policy == "review" and cue.get("preview_unreviewed_translation"):
                english = binding.text
                warnings.append("translation_review_required; unapproved English shown in draft")
            else:
                warnings.append(
                    "translation_review_required; unapproved English omitted from preview"
                )
    assets = data.get("assets", {})
    scene = caption_scene(
        excerpt,
        **data["canvas"],
        english=english,
        titles=data.get("titles", False),
        logo=str(_local_path(assets["logo"]["path"], root)) if "logo" in assets else "",
        arabic_title=cue.get("arabic_title", ""),
        latin_title=cue.get("latin_title", ""),
        title_surah=cue.get("title_surah"),
        logo_glyph=assets.get("logo", {}).get("glyph", ""),
    )
    scene = replace(scene, render_backend=data["render_backend"])
    profile_data = data.get(
        "profile",
        {
            "id": "plain",
            "revision": "1",
            "approval": "approved",
            "styles": {},
            "provenance": {},
        },
    )
    if (profile_data["id"], profile_data["revision"]) != (
        "plain",
        "1",
    ) and not profile_data["provenance"]:
        raise ReferenceError("invalid_profile", "Custom profiles require provenance")
    profile = CaptionProfile.from_dict(profile_data)
    if profile.approval != "approved":
        if data.get("require_approved_profile", False):
            raise ReferenceError(
                "profile_review", "Profile still requires creator approval"
            )
        warnings.append("profile_review_required")
    scene = profile.apply(scene)
    track_layers, track_records, track_warnings = resolve_tracks(
        tracks, cue, excerpt, root
    )
    annotation_layers, annotation_records = resolve_annotations(
        data, excerpt, track_records, root
    )
    warnings.extend(track_warnings)
    scene = replace(scene, layers=(*scene.layers, *track_layers, *annotation_layers))
    instance_specs = {
        item["track_id"]: ("translation_tracks", index, item)
        for index, item in enumerate(data.get("translation_tracks", []))
    }
    instance_specs.update(
        {
            item["annotation_id"]: ("annotations", index, item)
            for index, item in enumerate(data.get("annotations", []))
        }
    )
    if "quotes" in assets or "markers" in assets:
        scene = replace(scene, layers=tuple(replace(layer, decoration_layout="elements") if layer.role == "arabic" else layer for layer in scene.layers))
    if "decorations" in assets:
        decoration = assets["decorations"]
        path = str(_local_path(decoration["path"], root))
        checked_asset(path, decoration["sha256"])
        scene = replace(
            scene,
            layers=tuple(
                replace(
                    layer, decoration_font=path, decoration_sha256=decoration["sha256"]
                )
                if layer.role == "arabic"
                else layer
                for layer in scene.layers
            ),
        )
    scene = decorate_excerpt(
        excerpt,
        scene,
        quotations=data.get("quotations", False),
        verse_numbers=data.get("verse_numbers", False),
    )
    layers = []
    for layer in scene.layers:
        if not layer.instance_id and layer.role in assets:
            selector = assets[layer.role]
            path = str(_local_path(selector["path"], root))
            checked_asset(path, selector["sha256"])
            layer = (
                replace(layer, image=path, sha256=selector["sha256"])
                if layer.role == "logo" and not selector.get("glyph")
                else replace(layer, font=path, sha256=selector["sha256"])
            )
        if not layer.instance_id and layer.role == "translation" and dataset is not None:
            layer = replace(layer, direction=dataset.source.direction)
        if layer.font_fallbacks:
            layer = replace(layer, font_fallbacks=tuple({**selector, "path": str(_local_path(selector["path"], root))} for selector in layer.font_fallbacks))
        layers.append(layer)
    scene = replace(scene, layers=tuple(layers))
    from .typography import apply_break_hints

    scene = apply_break_hints(excerpt, scene, cue.get("line_breaks", []),
                             quotations=data.get("quotations", False), verse_numbers=data.get("verse_numbers", False))
    resolved_layers = []
    for layer in scene.layers:
        try:
            if layer.instance_id:
                Scene(scene.width, scene.height, (layer,)).validate()
            terms = instance_specs[layer.instance_id][2].get("font") if layer.instance_id else assets.get(layer.role)
            resolved_layers.append(font_workspace.prepare(layer, primary_terms=terms))
        except ReferenceError as error:
            error.details = getattr(error, "details", {})
            error.details["role"] = layer.role
            if layer.instance_id:
                collection, index, _ = instance_specs[layer.instance_id]
                error.details["layer_id"] = layer.instance_id
                field = error.details.get("field") or error.details.get("path", "").split("/")[-1] or "font"
                error.details["path"] = f"/{collection}/{index}/style/" + field + error.details.get("path_suffix", "")
            raise
    scene = replace(
        scene,
        layers=tuple(resolved_layers),
        groups=tuple(data.get("caption_groups", ())),
    )
    from .decoration_elements import prepare_element_fonts

    scene = replace(
        scene,
        layers=tuple(
            prepare_element_fonts(layer, assets, root, font_workspace)
            for layer in scene.layers
        ),
    )
    enforce_instance_layout(scene)
    scene_key = asdict(scene)
    for layer_data in scene_key["layers"]:
        layer_data["resolved_font"] = ""
        for font_data in layer_data.get("element_fonts", {}).values():
            font_data["resolved_font"] = ""
    plan_key = hashlib.sha256(canonical_bytes(scene_key)).hexdigest()
    cached_plans = cache.plans.get(plan_key) if cache else None
    if cached_plans is not None:
        # Input hashes, bindings and coverage were checked above on this request.
        # Rebind job-local font paths; no expired scratch file enters a cached plan.
        scene.validate()
        current = {layer.instance_id or layer.role: layer for layer in scene.layers}
        plans = tuple(
            plan
            if plan.layer.kind == "panel"
            else replace(
                plan,
                layer=current.get(
                    plan.layer.instance_id or plan.layer.role, plan.layer
                ),
            )
            for plan in cached_plans
        )
    else:
        plans = plan_scene(scene)
        if cache is not None:
            cache.plans.put(
                plan_key,
                plans,
                size=len(canonical_bytes({"plans": [asdict(plan) for plan in plans]})),
            )
    check_instance_collisions(plans)
    entry = {
            "cue_id": cue["cue_id"],
            "status": "needs_review" if warnings else "ready",
            "arabic": excerpt.text,
            "source_spans": [asdict(span) for span in excerpt.spans],
            "translation": translation,
            "metadata": cue.get("metadata", {}),
            "layers": [{**asdict(plan), "layer": _public_layer(plan.layer)} for plan in plans],
            "asset_ids": [],
            "warnings": warnings,
        }
    if "translation_tracks" in data:
        entry["translation_tracks"] = track_records
    if "annotations" in data:
        entry["annotations"] = annotation_records
    if data["operation"] == "inspect":
        from .style_contract import REFERENCE_FIELDS

        fields = style_schema()["properties"]
        from .scenes import dimension_scale
        styles = profile_data["styles"]
        entry["inspection"] = {"scale": scene.width / 576, "layers": [
            {"role": plan.layer.role, "instance_id": plan.layer.instance_id, "status": plan.status,
             "effective": {k: v for k, v in asdict(plan.layer).items() if k in fields},
             "origins": {k: "explicit" if k in (instance_specs[plan.layer.instance_id][2].get("style", {}) if plan.layer.instance_id in instance_specs else styles.get(plan.layer.role, {})) else "default" for k in fields},
             "resolved_pixels": {k: (tuple(v * dimension_scale(scene, plan.layer) for v in value) if isinstance(value, tuple) else value * dimension_scale(scene, plan.layer))
                                 for k, value in asdict(plan.layer).items() if k in REFERENCE_FIELDS},
             "fitted_font_size": plan.font_size, "scale": dimension_scale(scene, plan.layer), "layout": plan.layout_info}
            for plan in plans]}
        for inspected in entry["inspection"]["layers"]:
            original = instance_specs[inspected["instance_id"]][2].get("style", {}) if inspected["instance_id"] in instance_specs else styles.get(inspected["role"], {})
            inspected["nested_origins"] = {name: {field: "explicit" if field in original.get(name, {}) else "body"
                                                  for field in inspected["effective"].get(name, {})}
                                           for name in ("quotation_style", "marker_style")}
    return entry, scene, plans


def _public_layer(layer: Any) -> dict[str, Any]:
    data = asdict(layer)
    data["resolved_font"] = ""
    for font in data.get("element_fonts", {}).values():
        font["resolved_font"] = ""
    return data


def execute_request(
    request: RenderRequest | dict[str, Any],
    *,
    asset_root: Path | None = None,
    progress: Callable[[BatchProgress], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    deadline_seconds: float | None = None,
    cache: CaptionRenderCache | None = None,
) -> RenderResponse:
    """Execute one batch in one process; paths are rooted explicitly, no viewer/UI."""
    with FontWorkspace() as font_workspace:
        return _execute_request(
            request,
            asset_root=asset_root,
            progress=progress,
            cancelled=cancelled,
            deadline_seconds=deadline_seconds,
            font_workspace=font_workspace,
            cache=cache,
        )


def _execute_request(
    request: RenderRequest | dict[str, Any],
    *,
    asset_root: Path | None,
    progress: Callable[[BatchProgress], None] | None,
    cancelled: Callable[[], bool] | None,
    deadline_seconds: float | None,
    font_workspace: FontWorkspace,
    cache: CaptionRenderCache | None,
) -> RenderResponse:
    raw = request.payload if isinstance(request, RenderRequest) else request
    candidate = raw.get("request_id") if isinstance(raw, dict) else None
    request_id = (
        candidate if isinstance(candidate, str) and 0 < len(candidate) <= 128 else None
    )
    try:
        validated = RenderRequest.from_dict(
            request.to_dict() if isinstance(request, RenderRequest) else request
        )
        data = validated.payload
        request_id = data["request_id"]
        result: dict[str, Any] = {
            "schema_version": 1,
            "renderer_version": RENDERER_VERSION,
            "request_id": request_id,
            "status": "complete",
            "cues": [],
            "assets": [],
            "metadata": data.get("metadata", {}),
        }
        if data["operation"] == "capabilities":
            result["capabilities"] = capabilities(data["render_backend"])
            return RenderResponse(result)
        root = (asset_root or Path.cwd()).resolve()
        if data["operation"] == "inspect_fonts":
            if not data["assets"]:
                raise ReferenceError("missing_asset", "Select at least one pinned font to inspect")
            inspections = {}
            if data.get("profile"):
                CaptionProfile.from_dict(data["profile"])
            from .caption_editor import LAYER_ROLES, default_styles
            from .scenes import Layer
            from .style_contract import validate_layer_style

            for role, asset in data["assets"].items():
                style = {**(default_styles(role) if role in LAYER_ROLES else {}), **data.get("profile", {}).get("styles", {}).get(role, {})}
                validate_layer_style(Layer(role, **style), prefix="/profile/styles/" + role)
                preferred = style.get("font_size", 30)
                canvas = data.get("canvas", {"width": 576, "height": 1024})
                scale = 1 if style.get("scale_basis") == "pixels" else min(canvas.values()) / 576 if style.get("scale_basis") == "short_side" else canvas["width"] / 576
                effective_size = max(1, round(preferred * scale, 2) if isinstance(preferred, float) else round(preferred * scale))
                try:
                    inspections[role] = inspect_font(_local_path(asset["path"], root), sha256=asset["sha256"],
                        role=role, text=data.get("font_samples", {}).get(role, asset.get("glyph", "")), font_face=style.get("font_face", 0),
                        variation_axes=style.get("variation_axes", {}), font_size=effective_size,
                        license=asset["license"], attribution=asset["attribution"])
                except ReferenceError as error:
                    error.details = getattr(error, "details", {})
                    error.details["role"] = role
                    error.details["path"] = ("/profile/styles/" + role + "/" + error.details["field"] + error.details.get("path_suffix", "")
                                             if "field" in error.details else "/assets/" + role + ("/sha256" if error.code == "changed_asset" else "/path"))
                    raise
            result["font_inspection"] = inspections
            return RenderResponse(result)
        if data["operation"] in ("translation_catalog", "prepare_translations"):
            from .translation_api import prepare_translation_source, translation_catalog

            if data["operation"] == "translation_catalog":
                result["translation_catalog"] = translation_catalog(
                    data.get("translation_language"))
            else:
                result["translation_preparation"] = prepare_translation_source(
                    data, root, deadline_seconds=deadline_seconds, cancelled=cancelled)
            return RenderResponse(result)
        if data["operation"] == "preflight":
            from .preflight import preflight

            result["preflight"] = preflight(data, root)
            if data.get("cues"):
                preview = execute_request(
                    {**data, "operation": "layout"}, asset_root=root
                ).to_dict()
                preview["preflight"] = result["preflight"]
                preview["preflight"]["ready"] = preview["status"] == "complete"
                return RenderResponse(preview)
            return RenderResponse(result)
        corpus = CorpusIdentity(**data["source_corpus"])
        corpus.validate()
        dataset = (
            BindingDataset.from_dict(data["translation_dataset"])
            if "translation_dataset" in data
            else None
        )
        if "translation_snapshot" in data:
            pin = data["translation_snapshot"]
            dataset = SnapshotStore(_local_path(pin["directory"], root)).bindings(
                pin["sha256"]
            )
        control = BatchControl(
            deadline_seconds
            if deadline_seconds is not None
            else data.get("deadline_seconds", 300),
            cancelled,
            progress,
        )
        control.checkpoint("layout", 0, len(data["cues"]))
        tracks = prepare_tracks(
            data, root, lambda index: control.checkpoint("layout", 0, len(data["cues"]))
        )
        prepared = []
        word_jobs: dict[str, PreparedWords] = {}
        word_mask_bytes = 0
        layout_cache: OrderedDict[str, Any] = OrderedDict()
        for index, cue in enumerate(data["cues"]):
            control.checkpoint("layout", index, len(data["cues"]), cue["cue_id"])
            try:
                if "word_emphasis" in data and data.get("render_backend", "pillow") != "pillow":
                    raise ReferenceError("unsupported_word_emphasis_backend", "Layout-stable word emphasis currently requires Pillow RAQM", details={"path": "/word_emphasis", "backend": data["render_backend"]})
                cue_identity = {
                    k: v for k, v in cue.items() if k not in ("cue_id", "metadata", "word_states")
                }
                key = hashlib.sha256(canonical_bytes(cue_identity)).hexdigest()
                if key in layout_cache:
                    cached_entry, scene, plans = layout_cache[key]
                    entry = copy.deepcopy(cached_entry)
                    entry["cue_id"], entry["metadata"] = (
                        cue["cue_id"],
                        cue.get("metadata", {}),
                    )
                    layout_cache.move_to_end(key)
                else:
                    entry, scene, plans = _prepare_cue(
                        data, cue, root, dataset, font_workspace, tracks, cache
                    )
                    layout_cache[key] = (copy.deepcopy(entry), scene, plans)
                    if len(layout_cache) > 256:
                        layout_cache.popitem(last=False)
                if "word_states" in cue and "word_emphasis" not in data:
                    raise ReferenceError(
                        "invalid_word_selection", "Word states require word_emphasis configuration",
                        details={"path": "/word_emphasis"},
                    )
                if "word_emphasis" in data:
                    excerpt = select_excerpt(ExcerptRequest(
                        cue["cue_id"], tuple(SourceSpan(**span) for span in cue["spans"]),
                    ))
                    word_job = prepare_words(
                        excerpt, scene, plans,
                        {**data["word_emphasis"], "_quotations": data.get("quotations", False),
                         "_verse_numbers": data.get("verse_numbers", False)}, runtime_identity(),
                        partial(control.checkpoint, "layout", index, len(data["cues"]), cue["cue_id"]),
                    )
                    word_mask_bytes += sum(
                        len(part.alpha) for unit in word_job.units for part in unit.parts
                    )
                    if word_mask_bytes > 128 * 1024 * 1024:
                        raise ReferenceError(
                            "resource_limit", "Batch word masks exceed 128 MiB; split the job",
                            details={"path": "/word_emphasis"},
                        )
                    states = word_job.states(cue.get("word_states"))
                    entry["word_emphasis"] = {
                        **word_job.metadata(), "canvas": [scene.width, scene.height],
                        "states": [{"state_id": state_id, "asset_ids": [], "weights": [
                            {"unit_id": f"word:{i}", "weight": weight}
                            for i, weight in enumerate(weights)]} for state_id, weights in states],
                    }
                    word_jobs[cue["cue_id"]] = word_job
                prepared.append((entry, scene, plans))
                result["cues"].append(entry)
            except ReferenceError as error:
                if error.code in ("cancelled", "deadline_exceeded"):
                    raise
                details = getattr(error, "details", {})
                details["cue_id"] = cue["cue_id"]
                if "field" in details and "path" not in details and "role" in details:
                    details["path"] = "/profile/styles/" + details["role"] + "/" + details["field"] + details.get("path_suffix", "")
                if details.get("path", "").startswith("/line_breaks/"):
                    details["path"] = f"/cues/{index}" + details["path"]
                if details.get("path", "").startswith("/word_states/"):
                    details["path"] = f"/cues/{index}" + details["path"]
                if details.get("path", "").startswith("/track_bindings/"):
                    details["path"] = f"/cues/{index}" + details["path"]
                if details.get("layer_id") and details["layer_id"] in {item["track_id"] for item in data.get("translation_tracks", [])}:
                    details["track_id"] = details["layer_id"]
                if details.get("layer_id") and ("path" not in details or details["path"].startswith(("/layers/", "/profile/styles/"))):
                    for collection, key in (("translation_tracks", "track_id"), ("annotations", "annotation_id")):
                        for instance_index, spec in enumerate(data.get(collection, [])):
                            if spec[key] == details["layer_id"]:
                                field = details.get("field") or details.get("path", "").split("/")[-1] or "region"
                                details["path"] = f"/{collection}/{instance_index}/style/{field}" + details.get("path_suffix", "")
                if "role" in details and details.get("path", "").startswith("/layers/"):
                    details["path"] = "/profile/styles/" + details["path"][len("/layers/"):]
                error.details = details
                result["cues"].append(
                    {
                        "cue_id": cue["cue_id"],
                        "status": "failed",
                        "metadata": cue.get("metadata", {}),
                        "warnings": [],
                        "asset_ids": [],
                        "error": error_record(error),
                    }
                )
        failed = any(cue["status"] == "failed" for cue in result["cues"])
        result["status"] = (
            "partial"
            if failed and prepared
            else "failed"
            if failed
            else "needs_review"
            if any(cue["status"] == "needs_review" for cue in result["cues"])
            else "complete"
        )
        result["corpus"] = {
            "source": asdict(corpus),
            "target_sha256": TANZIL_TEXT_SHA256,
            "mapping_revision": MAPPING_REVISION,
            "mapping_sha256": BRIDGE_SHA256,
        }
        result["corpus"]["attribution"] = (
            "Tanzil Project, CC BY 3.0; original bundled notices preserved"
        )
        result["runtime"] = runtime_identity()
        result["profile"] = data.get(
            "profile", {"id": "plain", "revision": "1", "approval": "approved"}
        )
        result["profile"]["asset_provenance"] = data.get("assets", {})
        if data["operation"] != "render_batch" or not prepared:
            return RenderResponse(result)
        if failed and data.get("error_mode", "all_or_nothing") == "all_or_nothing":
            result["status"] = "failed"
            return RenderResponse(result)
        output = _local_path(data["output_directory"], root)
        output.mkdir(parents=True, exist_ok=True)
        disk_cache = (
            AssetCache(_local_path(data["asset_cache_directory"], root))
            if data.get("asset_cache_directory")
            else None
        )
        job_name = "job-" + uuid.uuid4().hex
        staging = Path(tempfile.mkdtemp(prefix=".pending-", dir=output))
        published = False
        try:
            shared: dict[str, dict[str, Any]] = {}
            output_bytes = 0
            for index, (entry, scene, plans) in enumerate(prepared):
                control.checkpoint("render", index, len(prepared), entry["cue_id"])
                try:
                    for plan_index, plan in enumerate(plans):
                        control.checkpoint(
                            "render", index, len(prepared), entry["cue_id"]
                        )
                        if plan.status != "ready":
                            entry["warnings"].append(
                                f"{plan.layer.role}: {plan.status}"
                            )
                            continue
                        visual_plan = asdict(plan)
                        visual_plan["layer"]["font"] = ""
                        visual_plan["layer"]["image"] = ""
                        visual_plan["layer"]["decoration_font"] = ""
                        visual_plan["layer"]["resolved_font"] = ""
                        for font in visual_plan["layer"].get("element_fonts", {}).values():
                            font["resolved_font"] = ""
                        identity = {
                            "scene_size": [scene.width, scene.height],
                            "plan": visual_plan,
                            "renderer": RENDERER_VERSION,
                            "runtime": result["runtime"],
                            "mapping": BRIDGE_SHA256,
                            "profile": result["profile"],
                            "cropped": data.get("cropped", False),
                        }
                        if not plan.layer.persistent:
                            identity["content"] = {
                                "source": entry["source_spans"],
                                "translation": entry["translation"],
                            }
                            instance_id = plan.layer.instance_id
                            if instance_id:
                                identity["content"]["translation_track"] = next((record for record in entry.get("translation_tracks", []) if record["track_id"] == instance_id), None)
                                identity["content"]["annotation"] = next((record for record in entry.get("annotations", []) if record["annotation_id"] == instance_id), None)
                        asset_id = hashlib.sha256(canonical_bytes(identity)).hexdigest()
                        if asset_id not in shared:
                            if len(shared) >= 512:
                                raise ReferenceError(
                                    "resource_limit",
                                    "Batch exceeds 512 unique assets; split the job",
                                )
                            path = staging / f"{asset_id}.png"
                            remembered = (
                                cache.assets.get(asset_id)
                                if cache and disk_cache is None
                                else None
                            )
                            if remembered is not None:
                                raw_png, asset = remembered
                                path.write_bytes(raw_png)
                            else:
                                asset = (
                                    disk_cache.restore(asset_id, path)
                                    if disk_cache
                                    else None
                                )
                            if asset is None:
                                asset = render_layer(
                                    scene,
                                    plan,
                                    path,
                                    cropped=data.get("cropped", False),
                                )
                                if disk_cache:
                                    disk_cache.store(asset_id, path, asset)
                            if cache is not None and remembered is None:
                                raw_png = path.read_bytes()
                                cache.assets.put(
                                    asset_id, (raw_png, asset), size=len(raw_png)
                                )
                            output_bytes += path.stat().st_size
                            if output_bytes > 512_000_000:
                                raise ReferenceError(
                                    "resource_limit",
                                    "Batch exceeds 512 MB of PNG output; split the job",
                                )
                            shared[asset_id] = {
                                "asset_id": asset_id,
                                "path": path.name,
                                **asdict(asset),
                                "roles": [plan.layer.role],
                                "persistent": plan.layer.persistent,
                                "effect_bounds": plan.bounds,
                                "anchor": plan.layer.anchor,
                                "font_sha256": plan.asset_sha256,
                            }
                            if plan.layer.instance_id:
                                shared[asset_id]["instance_ids"] = [plan.layer.instance_id]
                        entry["asset_ids"].append(asset_id)
                        entry["layers"][plan_index]["asset_id"] = asset_id
                    if entry["cue_id"] in word_jobs:
                        output_bytes += render_word_states(word_jobs[entry["cue_id"]], entry, shared, staging,
                            data.get("cropped", False), disk_cache, cache, output_bytes,
                            partial(control.checkpoint, "render", index, len(prepared), entry["cue_id"]))
                except Exception as error:
                    if isinstance(error, ReferenceError) and error.code in (
                        "cancelled",
                        "deadline_exceeded",
                    ):
                        raise
                    # A failed state may already have inserted reusable assets.
                    # Keep subsequent per-cue resource accounting exact too.
                    output_bytes = sum((staging / record["path"]).stat().st_size for record in shared.values())
                    failure = (
                        error
                        if isinstance(error, ReferenceError)
                        else ReferenceError(
                            "output_io"
                            if isinstance(error, OSError)
                            else "render_failed",
                            "Required layer production failed",
                        )
                    )
                    entry.update(
                        status="failed", asset_ids=[], error=error_record(failure)
                    )
                    for state in entry.get("word_emphasis", {}).get("states", []):
                        state["asset_ids"] = []
                    if data.get("error_mode", "all_or_nothing") == "all_or_nothing":
                        result.update(status="failed", assets=[])
                        return RenderResponse(result)
            used = {key for entry in result["cues"] for key in [*entry["asset_ids"],
                    *(asset_id for state in entry.get("word_emphasis", {}).get("states", []) for asset_id in state["asset_ids"])]}
            for key in set(shared) - used:
                (staging / shared[key]["path"]).unlink(missing_ok=True)
            result["assets"] = [record for key, record in shared.items() if key in used]
            failed = any(entry["status"] == "failed" for entry in result["cues"])
            result["status"] = (
                "partial"
                if failed and used
                else "failed"
                if failed
                else "needs_review"
                if any(entry["status"] == "needs_review" for entry in result["cues"])
                else "complete"
            )
            if not used:
                return RenderResponse(result)
            # Verify bytes and required input identities before publishing the manifest.
            for record in result["assets"]:
                if (
                    hashlib.sha256((staging / record["path"]).read_bytes()).hexdigest()
                    != record["sha256"]
                ):
                    raise ReferenceError(
                        "output_io", "Asset checksum changed before publication"
                    )
            inputs = {
                (plan.layer.image or plan.layer.font, plan.asset_sha256)
                for _, _, plans in prepared
                for plan in plans
                if plan.status == "ready" and plan.layer.kind != "panel"
            }
            inputs.update(
                (plan.layer.decoration_font, plan.decoration_asset_sha256)
                for _, _, plans in prepared
                for plan in plans
                if plan.status == "ready" and plan.layer.decoration_font
            )
            inputs.update((asset["path"], asset["sha256"])
                          for _, _, plans in prepared for plan in plans if plan.font_info
                          for asset in plan.font_info["inputs"])
            for path, digest in inputs:
                checked_asset(path, digest)
            control.checkpoint("publish", len(prepared), len(prepared))
            result["job_directory"] = str(output / job_name)
            (staging / "manifest.json").write_bytes(
                canonical_bytes(RenderResponse(result).to_dict())
            )
            staging.rename(output / job_name)
            published = True
        finally:
            if not published:
                shutil.rmtree(staging)
        return RenderResponse(result)
    except ReferenceError as error:
        response = failure_response(request_id, error)
        if error.code in ("cancelled", "deadline_exceeded") and "data" in locals():
            response.payload["cues"] = [
                {
                    "cue_id": cue["cue_id"],
                    "status": "failed",
                    "metadata": cue.get("metadata", {}),
                    "warnings": [],
                    "asset_ids": [],
                    "error": error_record(error),
                }
                for cue in data.get("cues", [])
            ]
        return response
    except (OSError, ValueError, TypeError) as error:
        return failure_response(
            request_id,
            ReferenceError(
                "output_io" if isinstance(error, OSError) else "invalid_request",
                "Output I/O failed"
                if isinstance(error, OSError)
                else "Malformed request or asset",
            ),
        )

    except Exception:
        return failure_response(
            request_id,
            ReferenceError(
                "render_failed", "Native rendering or asset decoding failed"
            ),
        )
