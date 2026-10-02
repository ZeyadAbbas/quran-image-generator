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
from pathlib import Path
from typing import Any

import jsonschema
import PIL
from PIL import features

from .batching import AssetCache, BatchControl, BatchProgress
from .bindings import BindingDataset
from .content import TANZIL_TEXT_SHA256
from .contract_schema import REQUEST_SCHEMA, RESPONSE_SCHEMA
from .excerpts import ExcerptRequest, select_excerpt
from .profiles import CaptionProfile, decorate_excerpt
from .references import (
    BRIDGE_SHA256,
    MAPPING_REVISION,
    CorpusIdentity,
    ReferenceError,
    SourceSpan,
)
from .scenes import (
    LayerPlan,
    Scene,
    caption_scene,
    checked_asset,
    plan_scene,
    render_layer,
)
from .snapshots import SnapshotStore, canonical_bytes

SCHEMA_VERSION = 1
RENDERER_VERSION = "0.2.0"
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
        try:
            jsonschema.Draft202012Validator(REQUEST_SCHEMA).validate(value)
        except jsonschema.ValidationError as error:
            raise ReferenceError(
                "invalid_request", "Request does not conform to request-v1.json"
            ) from error
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
    }


def capabilities() -> dict[str, Any]:
    return {
        "schema_versions": [1],
        "operations": ["capabilities", "validate", "layout", "render_batch"],
        "renderer_version": RENDERER_VERSION,
        "mapping_revision": MAPPING_REVISION,
        "mapping_sha256": BRIDGE_SHA256,
        "source_corpus": asdict(CorpusIdentity()),
        "target_corpus": {
            "edition": "Tanzil Uthmani Hafs",
            "version": "1.1",
            "sha256": TANZIL_TEXT_SHA256,
        },
        "profiles": [
            {"id": "plain", "revision": "1", "approval": "approved"},
            {
                "id": "islamstruebeauty",
                "revision": "1-preview",
                "approval": "needs_review",
            },
        ],
        "limits": {
            "request_bytes": MAX_REQUEST_BYTES,
            "cues": 1000,
            "spans_per_cue": 32,
            "layers": 16,
            "canvas_pixels": 8_500_000,
        },
        "alpha_mode": "straight",
        "color_space": "sRGB",
        "word_highlighting": False,
        "runtime": runtime_identity(),
    }


def error_record(error: ReferenceError) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": error.code,
        "message": str(error),
        "retryable": error.code in ("output_io", "translation_deadline"),
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
    )
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
    if (profile_data["id"], profile_data["revision"]) not in (
        ("plain", "1"),
        ("islamstruebeauty", "1-preview"),
    ) and not profile_data["provenance"]:
        raise ReferenceError("invalid_profile", "Custom profiles require provenance")
    profile = CaptionProfile(**profile_data)
    if profile.approval != "approved":
        if data.get("require_approved_profile", False):
            raise ReferenceError(
                "profile_review", "Profile still requires creator approval"
            )
        warnings.append("profile_review_required")
    scene = profile.apply(scene)
    scene = decorate_excerpt(
        excerpt,
        scene,
        quotations=data.get("quotations", False),
        verse_numbers=data.get("verse_numbers", False),
    )
    layers = []
    for layer in scene.layers:
        if layer.role in assets:
            selector = assets[layer.role]
            path = str(_local_path(selector["path"], root))
            checked_asset(path, selector["sha256"])
            layer = (
                replace(layer, image=path, sha256=selector["sha256"])
                if layer.role == "logo"
                else replace(layer, font=path, sha256=selector["sha256"])
            )
        if layer.role == "translation" and dataset is not None:
            layer = replace(layer, direction=dataset.source.direction)
        layers.append(layer)
    scene = replace(scene, layers=tuple(layers))
    plans = plan_scene(scene)
    return (
        {
            "cue_id": cue["cue_id"],
            "status": "needs_review" if warnings else "ready",
            "arabic": excerpt.text,
            "source_spans": [asdict(span) for span in excerpt.spans],
            "translation": translation,
            "metadata": cue.get("metadata", {}),
            "layers": [asdict(plan) for plan in plans],
            "asset_ids": [],
            "warnings": warnings,
        },
        scene,
        plans,
    )


def execute_request(
    request: RenderRequest | dict[str, Any],
    *,
    asset_root: Path | None = None,
    progress: Callable[[BatchProgress], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    deadline_seconds: float | None = None,
) -> RenderResponse:
    """Execute one batch in one process; paths are rooted explicitly, no viewer/UI."""
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
            result["capabilities"] = capabilities()
            return RenderResponse(result)
        root = (asset_root or Path.cwd()).resolve()
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
        prepared = []
        layout_cache: OrderedDict[str, Any] = OrderedDict()
        for index, cue in enumerate(data["cues"]):
            control.checkpoint("layout", index, len(data["cues"]), cue["cue_id"])
            try:
                cue_identity = {
                    k: v for k, v in cue.items() if k not in ("cue_id", "metadata")
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
                    entry, scene, plans = _prepare_cue(data, cue, root, dataset)
                    layout_cache[key] = (copy.deepcopy(entry), scene, plans)
                    if len(layout_cache) > 256:
                        layout_cache.popitem(last=False)
                prepared.append((entry, scene, plans))
                result["cues"].append(entry)
            except ReferenceError as error:
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
        cache = (
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
                    for plan in plans:
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
                        asset_id = hashlib.sha256(canonical_bytes(identity)).hexdigest()
                        if asset_id not in shared:
                            if len(shared) >= 512:
                                raise ReferenceError(
                                    "resource_limit",
                                    "Batch exceeds 512 unique assets; split the job",
                                )
                            path = staging / f"{asset_id}.png"
                            asset = cache.restore(asset_id, path) if cache else None
                            if asset is None:
                                asset = render_layer(
                                    scene,
                                    plan,
                                    path,
                                    cropped=data.get("cropped", False),
                                )
                                if cache:
                                    cache.store(asset_id, path, asset)
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
                        entry["asset_ids"].append(asset_id)
                except Exception as error:
                    if isinstance(error, ReferenceError) and error.code in (
                        "cancelled",
                        "deadline_exceeded",
                    ):
                        raise
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
                    if data.get("error_mode", "all_or_nothing") == "all_or_nothing":
                        result.update(status="failed", assets=[])
                        return RenderResponse(result)
            used = {key for entry in result["cues"] for key in entry["asset_ids"]}
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
                if plan.status == "ready"
            }
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
