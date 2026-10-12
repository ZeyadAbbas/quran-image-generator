"""Typed Python equivalents of the complete version 1 batch request."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .api import RenderRequest
from .bindings import BindingDataset
from .profiles import CaptionProfile
from .references import CorpusIdentity, SourceSpan


@dataclass(frozen=True, slots=True)
class Canvas:
    width: int = 576
    height: int = 1024


@dataclass(frozen=True, slots=True)
class AssetSelector:
    path: str
    sha256: str
    license: str
    attribution: str
    glyph: str | None = None


@dataclass(frozen=True, slots=True)
class TranslationSnapshot:
    directory: str
    sha256: str


@dataclass(frozen=True, slots=True)
class TrackBindingRef:
    binding_id: str
    revision: str


@dataclass(frozen=True, slots=True)
class TranslationTrack:
    track_id: str
    language: str = ""
    enabled: bool = True
    translation_policy: str = "required"
    preview_unreviewed_translation: bool = False
    dataset: BindingDataset | None = None
    snapshot: TranslationSnapshot | None = None
    binding: TrackBindingRef | None = None
    font: AssetSelector | None = None
    style: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Annotation:
    annotation_id: str
    kind: str = "source_reference"
    format: str = "words"
    text: str | None = None
    track_id: str | None = None
    approved: bool = False
    enabled: bool = True
    font: AssetSelector | None = None
    style: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CueRequest:
    cue_id: str
    spans: tuple[SourceSpan, ...]
    translation_policy: str = "none"
    translation_binding_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    title_surah: int | None = None
    arabic_title: str | None = None
    latin_title: str | None = None
    preview_unreviewed_translation: bool = False
    line_breaks: tuple[LineBreakHint, ...] = ()
    track_bindings: dict[str, TrackBindingRef] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LineBreakHint:
    span_occurrence: int
    source_word: int
    mode: str = "forced"


@dataclass(frozen=True, slots=True)
class BatchRequest:
    request_id: str
    cues: tuple[CueRequest, ...]
    canvas: Canvas = Canvas()
    source_corpus: CorpusIdentity = CorpusIdentity()
    operation: str = "layout"
    output_directory: str | None = None
    profile: CaptionProfile | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    assets: dict[str, AssetSelector] = field(default_factory=dict)
    translation_dataset: BindingDataset | None = None
    translation_snapshot: TranslationSnapshot | None = None
    titles: bool = False
    quotations: bool = False
    verse_numbers: bool = False
    cropped: bool = False
    asset_cache_directory: str | None = None
    deadline_seconds: float = 300
    error_mode: str = "all_or_nothing"
    require_approved_profile: bool = False
    caption_groups: tuple[dict[str, Any], ...] = ()
    translation_tracks: tuple[TranslationTrack, ...] = ()
    annotations: tuple[Annotation, ...] = ()

    def to_request(self) -> RenderRequest:
        payload = asdict(self)
        payload["schema_version"] = 1
        for key in (
            "output_directory",
            "profile",
            "translation_dataset",
            "translation_snapshot",
            "asset_cache_directory",
        ):
            if payload[key] is None:
                del payload[key]
        for cue in payload["cues"]:
            for key in (
                "translation_binding_id",
                "title_surah",
                "arabic_title",
                "latin_title",
            ):
                if cue[key] is None:
                    del cue[key]
        for asset in payload["assets"].values():
            if asset["glyph"] is None:
                del asset["glyph"]
        for collection in ("translation_tracks", "annotations"):
            if not payload[collection]:
                del payload[collection]
                continue
            for item in payload[collection]:
                for key in tuple(item):
                    if item[key] is None:
                        del item[key]
                if "font" in item and item["font"].get("glyph") is None:
                    item["font"].pop("glyph", None)
        return RenderRequest.from_dict(payload)
