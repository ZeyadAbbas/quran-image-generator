"""Explicit, source-pinned phrase translations; never infer semantic alignment."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .excerpts import ExcerptRequest, select_excerpt
from .references import MAPPING_REVISION, CorpusIdentity, ReferenceError, SourceSpan


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TranslationSource:
    provider: str
    resource: str
    version: str
    translator: str
    license: str
    attribution: str
    direction: str = "ltr"

    def __post_init__(self) -> None:
        if any(not isinstance(v, str) or not v.strip() for v in asdict(self).values()) or self.direction not in ("ltr", "rtl"):
            raise ReferenceError("invalid_translation", "Translation provenance and direction must be explicit")


@dataclass(frozen=True, slots=True)
class PhraseBinding:
    binding_id: str
    revision: str
    spans: tuple[SourceSpan, ...]
    arabic_sha256: str
    source_text: str
    source_text_sha256: str
    segments: tuple[str, ...]
    review_status: str
    reviewer: str
    edited: bool = False
    mapping_revision: str = MAPPING_REVISION

    @property
    def text(self) -> str:
        return "\n".join(self.segments)

    def validate(self, corpus: CorpusIdentity) -> None:
        if not self.binding_id or not self.revision or self.review_status not in ("approved", "needs_review"):
            raise ReferenceError("invalid_translation", "Binding ID/revision/review state is invalid")
        if self.review_status == "approved" and not self.reviewer.strip():
            raise ReferenceError("invalid_translation", "Approved bindings require a named reviewer")
        if not self.source_text.strip() or self.source_text_sha256 != text_hash(self.source_text):
            raise ReferenceError("stale_translation", "Source translation content hash changed")
        if not self.segments or any(not s.strip() or any(c in s for c in "<>\x00") for s in self.segments):
            raise ReferenceError("invalid_translation", "Use explicit plain caption segments; HTML/commentary is not automatically merged")
        if self.mapping_revision != MAPPING_REVISION:
            raise ReferenceError("stale_translation", "Binding mapping revision changed")
        arabic = select_excerpt(ExcerptRequest(self.binding_id, self.spans, corpus)).text
        if self.arabic_sha256 != text_hash(arabic):
            raise ReferenceError("stale_translation", "Binding Arabic content identity changed")


@dataclass(frozen=True, slots=True)
class BindingDataset:
    source: TranslationSource
    corpus: CorpusIdentity
    bindings: tuple[PhraseBinding, ...]
    schema_version: int = 1

    def validate(self) -> None:
        self.corpus.validate()
        if self.schema_version != 1 or len(self.bindings) > 10_000:
            raise ReferenceError("invalid_translation", "Unsupported binding dataset version/size")
        if len({b.binding_id for b in self.bindings}) != len(self.bindings):
            raise ReferenceError("invalid_translation", "Duplicate binding IDs")
        for binding in self.bindings:
            binding.validate(self.corpus)

    def lookup(self, binding_id: str, spans: tuple[SourceSpan, ...], *, require_approved: bool = True) -> PhraseBinding:
        self.validate()
        binding = next((b for b in self.bindings if b.binding_id == binding_id), None)
        if binding is None:
            raise ReferenceError("missing_translation", "Phrase binding is missing")
        if binding.spans != spans:
            raise ReferenceError("stale_translation", "Phrase binding does not match the exact ordered Arabic spans")
        if require_approved and binding.review_status != "approved":
            raise ReferenceError("translation_review", "Phrase translation requires semantic review")
        return binding

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BindingDataset:
        try:
            bindings = tuple(PhraseBinding(**{**b, "spans": tuple(SourceSpan(**s) for s in b["spans"]),
                                              "segments": tuple(b["segments"])}) for b in data["bindings"])
            result = cls(TranslationSource(**data["source"]), CorpusIdentity(**data["corpus"]), bindings, data["schema_version"])
            result.validate()
            return result
        except (KeyError, TypeError, AttributeError) as error:
            raise ReferenceError("invalid_translation", "Malformed binding dataset") from error


def import_bindings(path: Path) -> BindingDataset:
    if path.stat().st_size > 8_000_000:
        raise ReferenceError("invalid_translation", "Binding dataset exceeds 8 MB")
    try:
        return BindingDataset.from_dict(json.loads(path.read_text("utf-8-sig")))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ReferenceError("invalid_translation", "Binding dataset must be UTF-8 JSON") from error


def export_bindings(dataset: BindingDataset, path: Path) -> None:
    path.write_text(json.dumps(dataset.to_dict(), ensure_ascii=False, indent=2), "utf-8")
