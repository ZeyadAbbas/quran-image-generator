"""Bounded caption instances; verified wording stays separate from presentation."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .bindings import BindingDataset, text_hash
from .excerpts import Excerpt
from .references import ReferenceError, SourceSpan
from .resources import asset_path
from .scenes import Layer, Scene, checked_asset
from .snapshots import SnapshotStore

RESERVED_IDS = {"arabic", "translation", "arabic_title", "latin_title", "logo", "panel",
                "source_reference", "edition_label", "annotation"}


def validate_instances(data: dict[str, Any]) -> None:
    taken = set(RESERVED_IDS)
    for collection, key in (("translation_tracks", "track_id"), ("annotations", "annotation_id")):
        for index, item in enumerate(data.get(collection, [])):
            identity = item[key]
            path = f"/{collection}/{index}"
            if identity in taken or identity.startswith("group-panel"):
                raise ReferenceError("invalid_request", "Instance IDs must be unique and cannot use reserved layer IDs",
                                     details={"path": path + "/" + key, "layer_id": identity})
            taken.add(identity)
            if collection == "translation_tracks" and "dataset" in item and "snapshot" in item:
                raise ReferenceError("invalid_request", "Choose one dataset or pinned snapshot per track", details={"path": path})
            if item.get("font", {}).get("glyph"):
                raise ReferenceError("invalid_request", "Text instance fonts cannot specify a branding glyph", details={"path": path + "/font/glyph"})
            if collection == "annotations":
                if item["kind"] == "source_reference" and ("text" in item or "track_id" in item):
                    raise ReferenceError("invalid_annotation", "Source labels derive only from verified source spans", details={"path": path})
                if item["kind"] == "annotation" and (not item.get("text") or "track_id" in item):
                    raise ReferenceError("invalid_annotation", "General annotations require explicit presentation text", details={"path": path})
                if "text" in item and not item.get("approved", False):
                    raise ReferenceError("annotation_review", "Caller-supplied labels require explicit approval", details={"path": path + "/approved"})
                if "text" in item and (not item["text"].strip() or any(c in item["text"] for c in "<>\x00")):
                    raise ReferenceError("invalid_annotation", "Labels must be bounded plain text", details={"path": path + "/text"})
    tracks = {item["track_id"] for item in data.get("translation_tracks", [])}
    for index, annotation in enumerate(data.get("annotations", [])):
        if annotation["kind"] == "edition_label" and annotation.get("track_id") not in tracks:
            raise ReferenceError("invalid_annotation", "Edition labels must select an exact translation track",
                                 details={"path": f"/annotations/{index}/track_id"})
    for index, cue in enumerate(data.get("cues", [])):
        unknown = set(cue.get("track_bindings", {})) - tracks
        if unknown:
            identity = sorted(unknown)[0]
            raise ReferenceError("invalid_request", "Unknown translation track binding",
                                 details={"path": f"/cues/{index}/track_bindings/{identity}", "track_id": identity})


def local_path(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


@dataclass(frozen=True)
class PreparedTrack:
    spec: dict[str, Any]
    index: int
    dataset: BindingDataset | None
    error: ReferenceError | None = None


def prepare_tracks(data: dict[str, Any], root: Path, checkpoint: Callable[[int], None] | None = None) -> tuple[PreparedTrack, ...]:
    """Validate each dataset once per batch, without any render-time download."""
    result = []
    for index, spec in enumerate(data.get("translation_tracks", [])):
        if checkpoint:
            checkpoint(index)
        dataset = None
        error = None
        if spec.get("enabled", True) and spec.get("style", {}).get("enabled", True) and spec.get("translation_policy", "required") != "none":
            try:
                if "dataset" in spec:
                    dataset = BindingDataset.from_dict(spec["dataset"])
                elif "snapshot" in spec:
                    pin = spec["snapshot"]
                    dataset = SnapshotStore(local_path(pin["directory"], root)).bindings(pin["sha256"])
                if dataset is not None and asdict(dataset.corpus) != data["source_corpus"]:
                    raise ReferenceError("stale_translation", "Track corpus identity does not match the request")
                if dataset is not None and spec.get("style", {}).get("direction", dataset.source.direction) != dataset.source.direction:
                    raise ReferenceError("invalid_request", "Track direction must match its pinned source", details={"path": f"/translation_tracks/{index}/style/direction"})
            except ReferenceError as failure:
                error = failure
            except (OSError, ValueError, KeyError, TypeError):
                error = ReferenceError("invalid_translation", "Track dataset or snapshot cannot be read as a pinned binding dataset")
        result.append(PreparedTrack(spec, index, dataset, error))
    return tuple(result)


def instance_layer(role: str, identity: str, text: str, spec: dict[str, Any], root: Path,
                   *, direction: str = "ltr", z_order: int = 1, size: int = 16) -> Layer:
    selector = spec.get("font")
    font = str(local_path(selector["path"], root)) if selector else str(asset_path("fonts", "multilingual_fonts", "am.ttf"))
    layer = Layer(role, text, font, instance_id=identity, direction=direction, font_size=size,
                  min_font_size=min(12, size), anchor=(0.5, 0.5), region=(0.05, 0.05, 0.95, 0.95),
                  z_order=z_order, required=True, baseline_anchor="first")
    layer = replace(layer, **spec.get("style", {}))
    # Visual required=false or direction must never weaken the wording contract.
    return replace(layer, enabled=spec.get("enabled", True) and layer.enabled,
                   direction=direction if role == "translation" else layer.direction,
                   required=bool(text) and layer.required,
                   sha256=selector["sha256"] if selector else layer.sha256)


def resolve_tracks(tracks: tuple[PreparedTrack, ...], cue: dict[str, Any], excerpt: Excerpt,
                   root: Path) -> tuple[list[Layer], list[dict[str, Any]], list[str]]:
    layers, records, warnings = [], [], []
    spans = tuple(SourceSpan(**span) for span in cue["spans"])
    for prepared in tracks:
        spec, dataset = prepared.spec, prepared.dataset
        identity = spec["track_id"]
        path = f"/translation_tracks/{prepared.index}"
        reference = cue.get("track_bindings", {}).get(identity, spec.get("binding"))
        binding_path = f"/track_bindings/{identity}" if identity in cue.get("track_bindings", {}) else path + "/binding"
        policy = spec.get("translation_policy", "required")
        enabled = spec.get("enabled", True) and spec.get("style", {}).get("enabled", True)
        record: dict[str, Any] = {"track_id": identity, "status": "disabled" if not enabled or policy == "none" else "omitted_optional",
                                  "language": spec.get("language", ""),
                                  "source": asdict(dataset.source) if dataset else None, "binding": None,
                                  "font": copy.deepcopy(spec.get("font")), "metadata": spec.get("metadata", {}),
                                  "policy": policy, "snapshot": copy.deepcopy(spec.get("snapshot"))}
        text = ""
        try:
            if enabled and policy != "none":
                if prepared.error is not None:
                    raise ReferenceError(prepared.error.code, str(prepared.error), details={"path": path + ("/snapshot" if "snapshot" in spec else "/dataset"), **getattr(prepared.error, "details", {})})
                binding = next((b for b in dataset.bindings if reference and b.binding_id == reference["binding_id"]), None) if dataset else None
                if binding is None:
                    if policy == "required":
                        raise ReferenceError("missing_translation", "Required track dataset or exact binding is missing", details={"path": binding_path})
                    warnings.append(identity + ": translation_review_required; absent optional track omitted")
                else:
                    if binding.spans != spans or binding.arabic_sha256 != text_hash(excerpt.text):
                        raise ReferenceError("stale_translation", "Track binding does not match the exact ordered source spans", details={"path": binding_path})
                    if reference is None or binding.revision != reference["revision"]:
                        raise ReferenceError("stale_translation", "Track binding revision changed", details={"path": binding_path + "/revision"})
                    record["binding"] = asdict(binding)
                    if binding.review_status != "approved":
                        if policy == "required":
                            raise ReferenceError("translation_review", "Required track needs semantic review", details={"path": binding_path})
                        record["status"] = "needs_review"
                        if spec.get("preview_unreviewed_translation", False):
                            text = binding.text
                        warnings.append(identity + ": translation_review_required; draft " + ("shown" if text else "omitted"))
                    else:
                        record["status"], text = "ready", binding.text
            layer = instance_layer("translation", identity, text, spec, root,
                                   direction=dataset.source.direction if dataset else "ltr", z_order=prepared.index + 1)
            if not enabled or policy == "none":
                layer = replace(layer, enabled=False)
            if layer.enabled and layer.text and "font" in spec:
                checked_asset(layer.font, spec["font"]["sha256"])
            layers.append(layer)
            record["displayed"] = bool(layer.text and layer.enabled)
            records.append(record)
        except ReferenceError as error:
            error.details = {**getattr(error, "details", {}), "track_id": identity, "layer_id": identity}
            error.details.setdefault("path", path + "/font/" + ("sha256" if error.code == "changed_asset" else "path") if error.code in ("changed_asset", "missing_asset") else path)
            raise
    return layers, records, warnings


def source_reference(excerpt: Excerpt, format: str) -> str:
    from .content import QuranDataClient

    parts = []
    for span in excerpt.spans:
        source = span.source
        if source.surah == 0:
            parts.append(f"Basmala (words {source.word_start}-{source.word_end})")
            continue
        label = f"{source.surah}:{source.ayah}"
        if format == "named":
            label = QuranDataClient().get_chapter(source.surah).name_simple + " " + label
        # A compact label must still disclose partial selection.
        if format != "compact" or not (span.starts_ayah and span.ends_ayah):
            label += f" (words {source.word_start}-{source.word_end})"
        parts.append(label)
    return "; ".join(parts)


def resolve_annotations(data: dict[str, Any], excerpt: Excerpt, records: list[dict[str, Any]], root: Path) -> tuple[list[Layer], list[dict[str, Any]]]:
    layers, labels = [], []
    by_id = {record["track_id"]: record for record in records}
    for index, spec in enumerate(data.get("annotations", [])):
        text, enabled = "", spec.get("enabled", True)
        kind = spec["kind"]
        if kind == "source_reference":
            text = source_reference(excerpt, spec.get("format", "words"))
        elif kind == "edition_label":
            record = by_id[spec["track_id"]]
            enabled = enabled and record["displayed"]
            if record["source"]:
                source = record["source"]
                text = spec.get("text", f"{source['translator']} — {source['resource']} ({source['version']})")
        else:
            text = spec["text"]
        if len(text) > 512:
            raise ReferenceError("invalid_annotation", "Derived label exceeds 512 characters; use compact references or shorter approved edition text", details={"path": f"/annotations/{index}", "layer_id": spec["annotation_id"]})
        layer = instance_layer(kind, spec["annotation_id"], text if enabled else "", spec, root, z_order=10 + index, size=12)
        layer = replace(layer, enabled=enabled and layer.enabled)
        if layer.enabled and layer.text and "font" in spec:
            try:
                checked_asset(layer.font, spec["font"]["sha256"])
            except ReferenceError as error:
                error.details = {"path": f"/annotations/{index}/font/" + ("sha256" if error.code == "changed_asset" else "path"), "layer_id": spec["annotation_id"]}
                raise
        layers.append(layer)
        labels.append({"annotation_id": spec["annotation_id"], "kind": kind, "text": text,
                       "approved": spec.get("approved", False) if "text" in spec else True,
                       "track_id": spec.get("track_id"), "font": spec.get("font"), "enabled": layer.enabled})
    return layers, labels


def enforce_instance_layout(scene: Scene) -> None:
    """New instances require declared flow or collision checking; legacy is unchanged."""
    active = {layer.instance_id for layer in scene.layers if layer.instance_id and layer.enabled and layer.text}
    covered = {identity for group in scene.groups if group.get("mode") == "flow" or group.get("collision") == "reject"
               for identity in group["layers"]}
    if active - covered:
        identity = sorted(active - covered)[0]
        raise ReferenceError("missing_group_layout", "New caption instances require an explicit flow group or collision=reject group",
                             details={"path": "/caption_groups", "layer_id": identity,
                                      "suggestions": ["Declare an ordered flow group including Arabic and enabled instance IDs", "Declare positioned layers in a collision=reject group"]})


def check_instance_collisions(plans: tuple[Any, ...]) -> None:
    active = [plan for plan in plans if plan.status == "ready" and plan.bounds and plan.layer.kind != "panel"]
    for index, left in enumerate(active):
        for right in active[index + 1:]:
            if not (left.layer.instance_id or right.layer.instance_id):
                continue
            a, b = left.bounds, right.bounds
            if max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3]):
                identity = left.layer.instance_id or right.layer.instance_id
                raise ReferenceError("layer_collision", "Caption instance intersects another effect/panel envelope",
                                     details={"path": "/caption_groups", "layer_id": identity,
                                              "layers": [left.layer.instance_id or left.layer.role, right.layer.instance_id or right.layer.role],
                                              "bounds": [a, b], "constraint": "collision"})
