"""Display-independent document operations for the general desktop caption editor."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PIL import Image

from .api import MAX_REQUEST_BYTES, RenderRequest
from .bindings import BindingDataset, PhraseBinding, TranslationSource, text_hash
from .contract_schema import style_schema
from .excerpts import ExcerptRequest, select_excerpt
from .profiles import CaptionProfile
from .references import CorpusIdentity, ReferenceError, SourceSpan, bridge_data
from .scenes import caption_scene, checked_asset
from .snapshots import SnapshotStore

LAYER_ROLES = ("arabic", "translation", "arabic_title", "latin_title", "logo")
ASSET_ROLES = (*LAYER_ROLES, "decorations", "quotes", "markers")
STYLE_FIELDS = style_schema()["properties"]


def parse_style_value(name: str, value: Any) -> Any:
    """Parse native controls using the published field types, never eval."""
    spec = STYLE_FIELDS[name]
    kind = spec.get("type")
    try:
        if kind == "object" or name in ("font_features", "font_fallbacks"):
            result = json.loads(str(value))
            from .diagnostics import validate_schema

            validate_schema(result, spec, code="invalid_profile", prefix="/profile/styles/" + name)
            return result
        if kind == "boolean":
            if type(value) is not bool:
                raise ValueError("Expected a checkbox value")
            return value
        if kind == "integer":
            return int(str(value).strip())
        if kind == "number":
            result = float(value)
            json.dumps(result, allow_nan=False)
            return result
        if kind == "array":
            parts = [float(v.strip()) for v in str(value).split(",")]
            if len(parts) != spec["minItems"]:
                raise ValueError("Wrong number of coordinates")
            json.dumps(parts, allow_nan=False)
            return parts
        return str(value)
    except (ValueError, TypeError) as error:
        raise ReferenceError(
            "invalid_profile", f"Invalid {name.replace('_', ' ')}"
        ) from error


def default_styles(role: str) -> dict[str, Any]:
    excerpt = select_excerpt(ExcerptRequest("default", (SourceSpan(1, 1, 1, 4),)))
    scene = caption_scene(excerpt, english="Caption", titles=True, logo="unused.png")
    layer = next(layer for layer in scene.layers if layer.role == role)
    return {k: v for k, v in asdict(layer).items() if k in STYLE_FIELDS}


class CaptionDocument:
    """One ordinary schema-1 request, with no consumer-specific presets."""

    def __init__(
        self, data: dict[str, Any] | None = None, *, root: Path | None = None
    ) -> None:
        self.root = (root or Path.cwd()).resolve()
        self.data = RenderRequest.from_dict(
            data
            if data is not None
            else {
                "schema_version": 1,
                "request_id": "captions",
                "operation": "render_batch",
                "source_corpus": asdict(CorpusIdentity()),
                "canvas": {"width": 576, "height": 1024},
                "output_directory": str(self.root / "caption output"),
                "cues": [
                    {"cue_id": "caption-1", "spans": [asdict(SourceSpan(1, 1, 1, 4))]}
                ],
            }
        ).to_dict()
        for key in ("output_directory", "asset_cache_directory"):
            if self.data.get(key):
                self.data[key] = str(self.resolve(self.data[key]))
        for asset in self.data.get("assets", {}).values():
            asset["path"] = str(self.resolve(asset["path"]))
        for style in self.data.get("profile", {}).get("styles", {}).values():
            for settings in (style, style.get("quotation_style", {}), style.get("marker_style", {})):
                for fallback in settings.get("font_fallbacks", []):
                    fallback["path"] = str(self.resolve(fallback["path"]))
        if "translation_snapshot" in self.data:
            pin = self.data["translation_snapshot"]
            pin["directory"] = str(self.resolve(pin["directory"]))
        for collection in ("translation_tracks", "annotations"):
            for item in self.data.get(collection, []):
                if "font" in item:
                    item["font"]["path"] = str(self.resolve(item["font"]["path"]))
                if "snapshot" in item:
                    item["snapshot"]["directory"] = str(self.resolve(item["snapshot"]["directory"]))
                for fallback in item.get("style", {}).get("font_fallbacks", []):
                    fallback["path"] = str(self.resolve(fallback["path"]))

    def resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (self.root / path).resolve()

    @classmethod
    def load(cls, path: Path) -> CaptionDocument:
        if path.stat().st_size > MAX_REQUEST_BYTES:
            raise ReferenceError("invalid_request", "Caption document exceeds 8 MB")
        try:
            return cls(json.loads(path.read_text("utf-8-sig")), root=path.parent)
        except (UnicodeError, ValueError) as error:
            if isinstance(error, ReferenceError):
                raise
            raise ReferenceError(
                "invalid_request", "Use a UTF-8 caption request file"
            ) from error

    def request(self, operation: str = "render_batch") -> RenderRequest:
        return RenderRequest.from_dict({**self.data, "operation": operation})

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.request().to_dict(), ensure_ascii=False, indent=2), "utf-8"
        )

    def profile(self) -> dict[str, Any]:
        profile: dict[str, Any] = self.data.setdefault(
            "profile",
            {
                "id": "custom",
                "revision": "1",
                "approval": "needs_review",
                "styles": {},
                "provenance": {"author": "Desktop caption editor"},
            },
        )
        return profile

    def styles(self, role: str) -> dict[str, Any]:
        return {
            **default_styles(role),
            **self.data.get("profile", {}).get("styles", {}).get(role, {}),
        }

    def set_style(self, role: str, values: dict[str, Any]) -> None:
        if role not in LAYER_ROLES:
            raise ReferenceError("invalid_profile", "Unknown layer")
        candidate = copy.deepcopy(self.profile())
        candidate["styles"][role] = values
        CaptionProfile.from_dict(candidate)
        self.data["profile"] = candidate

    def set_asset(
        self, role: str, path: str, license: str, attribution: str, glyph: str = ""
    ) -> None:
        if role not in ASSET_ROLES:
            raise ReferenceError("invalid_request", "Unknown asset role")
        assets = self.data.setdefault("assets", {})
        if not path.strip():
            assets.pop(role, None)
            self.profile()["styles"].get(role, {}).pop("sha256", None)
            return
        resolved = self.resolve(path)
        asset = {
            "path": str(resolved),
            "sha256": checked_asset(str(resolved)),
            "license": license,
            "attribution": attribution,
        }
        if glyph:
            if role != "logo":
                raise ReferenceError(
                    "invalid_request", "Only the branding font accepts a glyph"
                )
            asset["glyph"] = glyph
        assets[role] = asset
        if role in self.profile()["styles"]:
            self.profile()["styles"][role]["sha256"] = asset["sha256"]

    def duplicate_cue(self, index: int) -> int:
        cue = copy.deepcopy(self.data["cues"][index])
        taken = {c["cue_id"] for c in self.data["cues"]}
        suffix = 2
        while f"{cue['cue_id']}-{suffix}" in taken:
            suffix += 1
        cue["cue_id"] = f"{cue['cue_id']}-{suffix}"
        self.data["cues"].insert(index + 1, cue)
        return index + 1

    def add_span(self, index: int, span: SourceSpan) -> None:
        spans = (*self.spans(index), span)
        select_excerpt(ExcerptRequest("selection", spans))
        self.data["cues"][index]["spans"] = [asdict(s) for s in spans]

    def spans(self, index: int) -> tuple[SourceSpan, ...]:
        return tuple(SourceSpan(**s) for s in self.data["cues"][index]["spans"])

    def arabic(self, index: int) -> str:
        return select_excerpt(ExcerptRequest("selection", self.spans(index))).text

    def validate_line_breaks(self, index: int, hints: list[dict[str, Any]]) -> None:
        from .contract_schema import CUE
        from .diagnostics import validate_schema
        from .typography import apply_break_hints

        validate_schema(hints, CUE["properties"]["line_breaks"], prefix=f"/cues/{index}/line_breaks")
        excerpt = select_excerpt(ExcerptRequest("selection", self.spans(index)))
        apply_break_hints(excerpt, caption_scene(excerpt), hints, quotations=False, verse_numbers=False)

    def set_line_breaks(self, index: int, hints: list[dict[str, Any]]) -> None:
        self.validate_line_breaks(index, hints)
        self.data["cues"][index]["line_breaks"] = copy.deepcopy(hints)

    def set_caption_groups(self, groups: list[dict[str, Any]]) -> None:
        candidate = copy.deepcopy(self.data)
        candidate["caption_groups"] = groups
        RenderRequest.from_dict(candidate)
        if len({group["group_id"] for group in groups}) != len(groups):
            raise ReferenceError("invalid_group", "Caption group IDs must be unique")
        self.data["caption_groups"] = copy.deepcopy(groups)

    def set_caption_instances(self, tracks: list[dict[str, Any]], annotations: list[dict[str, Any]],
                              bindings: dict[str, Any], cue_index: int) -> None:
        candidate = copy.deepcopy(self.data)
        candidate["translation_tracks"] = tracks
        candidate["annotations"] = annotations
        candidate["cues"][cue_index]["track_bindings"] = bindings
        # Re-root pins just as when opening a saved request. No wording approval changes.
        normalized = CaptionDocument(candidate, root=self.root)
        self.data = normalized.data

    @staticmethod
    def word_count(surah: int, ayah: int) -> int:
        if (surah, ayah) == (0, 0):
            return 4
        verse = bridge_data()["verses"].get(f"{surah}:{ayah}")
        if verse is None:
            raise ReferenceError(
                "invalid_reference", "This chapter/verse is unavailable"
            )
        return int(verse["word_count"])

    def dataset(self) -> BindingDataset | None:
        if "translation_dataset" in self.data:
            return BindingDataset.from_dict(self.data["translation_dataset"])
        if "translation_snapshot" in self.data:
            pin = self.data["translation_snapshot"]
            return SnapshotStore(self.resolve(pin["directory"])).bindings(pin["sha256"])
        return None

    def set_dataset(self, dataset: BindingDataset) -> None:
        self.data["translation_dataset"] = dataset.to_dict()
        self.data.pop("translation_snapshot", None)

    def pin_snapshot(self, directory: Path, digest: str) -> None:
        SnapshotStore(directory).bindings(digest)
        self.data.pop("translation_dataset", None)
        self.data["translation_snapshot"] = {
            "directory": str(directory.resolve()),
            "sha256": digest,
        }

    def bind(
        self,
        index: int,
        source: TranslationSource,
        *,
        binding_id: str,
        revision: str,
        source_text: str,
        segments: tuple[str, ...],
        approved: bool,
        reviewer: str,
        edited: bool,
    ) -> None:
        if "translation_snapshot" in self.data:
            raise ReferenceError(
                "invalid_translation",
                "Use Edit a local copy before changing a pinned snapshot",
            )
        binding = PhraseBinding(
            binding_id,
            revision,
            self.spans(index),
            text_hash(self.arabic(index)),
            source_text,
            text_hash(source_text),
            segments,
            "approved" if approved else "needs_review",
            reviewer,
            edited,
            source_identity_sha256=source.identity_sha256,
        )
        old = self.dataset()
        bindings = (
            tuple(b for b in old.bindings if b.binding_id != binding_id) if old else ()
        )
        self.set_dataset(
            BindingDataset(
                source,
                CorpusIdentity(**self.data["source_corpus"]),
                (*bindings, binding),
            )
        )
        self.data["cues"][index]["translation_binding_id"] = binding_id


def compose_caption(
    response: dict[str, Any], cue_index: int, size: tuple[int, int]
) -> Image.Image:
    """Recompose the exact exported assets, honoring offsets and checksums."""
    cue = response["cues"][cue_index]
    if cue["status"] == "failed":
        raise ReferenceError(cue["error"]["code"], cue["error"]["message"])
    records = {asset["asset_id"]: asset for asset in response["assets"]}
    canvas = Image.new("RGBA", size)
    for key in cue["asset_ids"]:
        record = records[key]
        path = Path(response["job_directory"]) / record["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ReferenceError("changed_asset", "An exported preview asset changed")
        with Image.open(path) as image:
            canvas.alpha_composite(image, tuple(record["offset"]))
    return canvas
