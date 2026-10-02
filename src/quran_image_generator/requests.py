"""Typed Python equivalents of common version 1 batch requests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .api import RenderRequest
from .profiles import CaptionProfile
from .references import CorpusIdentity, SourceSpan


@dataclass(frozen=True, slots=True)
class Canvas:
    width: int = 576
    height: int = 1024


@dataclass(frozen=True, slots=True)
class CueRequest:
    cue_id: str
    spans: tuple[SourceSpan, ...]
    translation_policy: str = "none"
    translation_binding_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


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

    def to_request(self) -> RenderRequest:
        payload = asdict(self)
        payload["schema_version"] = 1
        for key in ("output_directory", "profile"):
            if payload[key] is None:
                del payload[key]
        for cue in payload["cues"]:
            if cue["translation_binding_id"] is None:
                del cue["translation_binding_id"]
        return RenderRequest.from_dict(payload)
