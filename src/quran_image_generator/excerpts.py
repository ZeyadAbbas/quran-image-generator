"""Validated phrase selection, independent of recognition text or cue timings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .references import (
    CorpusIdentity,
    ReferenceError,
    ResolvedSpan,
    SourceSpan,
    resolve_span,
)


@dataclass(frozen=True, slots=True)
class ExcerptRequest:
    cue_id: str
    spans: tuple[SourceSpan, ...]
    corpus: CorpusIdentity = CorpusIdentity()
    translation_policy: Literal["none", "review", "required"] = "none"
    translation_binding_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.cue_id, str) or not self.cue_id.strip() or len(self.cue_id) > 128:
            raise ReferenceError("invalid_request", "cue_id must contain 1..128 characters")
        if not self.spans or len(self.spans) > 32:
            raise ReferenceError("invalid_reference", "An excerpt needs 1..32 ordered spans")
        if self.translation_policy not in ("none", "review", "required"):
            raise ReferenceError("invalid_request", "Unknown translation policy")
        if self.translation_policy == "required" and not self.translation_binding_id:
            raise ReferenceError("missing_translation", "A phrase-specific translation binding is required")


@dataclass(frozen=True, slots=True)
class Excerpt:
    cue_id: str
    spans: tuple[ResolvedSpan, ...]
    translation_status: str

    @property
    def text(self) -> str:
        return " ".join(span.text for span in self.spans)

    @property
    def verse_markers(self) -> tuple[tuple[int, int], ...]:
        """Index of completed span and actual ayah; basmala has no end number."""
        return tuple((i, span.source.ayah) for i, span in enumerate(self.spans)
                     if span.ends_ayah and span.source.surah != 0)


def select_excerpt(request: ExcerptRequest) -> Excerpt:
    request.corpus.validate()
    resolved = tuple(resolve_span(span, request.corpus) for span in request.spans)
    status = {"none": "disabled", "review": "needs_review", "required": "binding_required"}[request.translation_policy]
    return Excerpt(request.cue_id, resolved, status)


def select_excerpts(requests: tuple[ExcerptRequest, ...]) -> tuple[Excerpt, ...]:
    if len({r.cue_id for r in requests}) != len(requests):
        raise ReferenceError("duplicate_cue_id", "Each occurrence needs a unique cue ID")
    return tuple(select_excerpt(request) for request in requests)
