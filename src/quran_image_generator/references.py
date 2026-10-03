"""Edition-qualified references into verbatim, integrity-checked Quran text."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from .content import TANZIL_TEXT_SHA256, _load_bundled_corpus, _package_bytes

SIMPLE_SHA256 = "f3268cfe7a400add8a8024fe23368d66f58cc8baa51773fe94e323625c66344b"
MAPPING_REVISION = "simple-uthmani-4"
# Replaced by the reproducible builder's payload digest.
BRIDGE_SHA256 = "fd2427b84d0476f2547bd7e40feb40985b77692ddbe60477351cc320fae8621a"


class ReferenceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CorpusIdentity:
    edition: str = "Tanzil Simple Hafs"
    version: str = "1.1"
    sha256: str = SIMPLE_SHA256

    def validate(self) -> None:
        if self != CorpusIdentity():
            raise ReferenceError("unsupported_corpus", "Unsupported caller edition/version/hash")


@dataclass(frozen=True, slots=True)
class SourceSpan:
    surah: int
    ayah: int
    word_start: int
    word_end: int

    def __post_init__(self) -> None:
        values = (self.surah, self.ayah, self.word_start, self.word_end)
        if any(type(v) is not int for v in values) or self.surah < 0 or self.ayah < 0 or self.word_start < 1 or self.word_end < self.word_start:
            raise ReferenceError("invalid_reference", "Expected inclusive 1-based word references (basmala is 0:0)")


@dataclass(frozen=True, slots=True)
class ResolvedSpan:
    source: SourceSpan
    text: str
    target_verse: str
    character_start: int
    character_end: int
    starts_ayah: bool
    ends_ayah: bool
    mapping_revision: str = MAPPING_REVISION
    target_sha256: str = TANZIL_TEXT_SHA256


@lru_cache(maxsize=1)
def bridge_data() -> dict[str, Any]:
    raw = _package_bytes("assets/data/simple-uthmani-bridge.json")
    if hashlib.sha256(raw).hexdigest() != BRIDGE_SHA256:
        raise ReferenceError("corrupt_mapping", "Mapping failed integrity verification")
    data: dict[str, Any] = json.loads(raw)
    if data["source_sha256"] != SIMPLE_SHA256 or data["target_sha256"] != TANZIL_TEXT_SHA256:
        raise ReferenceError("corrupt_mapping", "Mapping corpus identity mismatch")
    return data


def resolve_span(span: SourceSpan, corpus: CorpusIdentity | None = None) -> ResolvedSpan:
    (corpus or CorpusIdentity()).validate()
    key = f"{span.surah}:{span.ayah}"
    record = bridge_data()["verses"].get(key)
    if record is None or span.word_end > record["word_count"]:
        raise ReferenceError("invalid_reference", f"Unknown or out-of-bounds range {key}")
    target_key = (1, 1) if key == "0:0" else (span.surah, span.ayah)
    text = _load_bundled_corpus().verses[target_key]
    full = span.word_start == 1 and span.word_end == record["word_count"]
    if full:
        start, end = record["offset"], len(text)
    else:
        selected = [g for g in record["groups"] if g[1] >= span.word_start and g[0] <= span.word_end]
        if not selected or any(not g[4] for g in selected) or selected[0][0] != span.word_start or selected[-1][1] != span.word_end:
            raise ReferenceError("mapping_boundary", f"Range {key} touches a joined word or unresolved spelling; select a verified group or review the mapping")
        start, end = selected[0][2], selected[-1][3]
    # Remove separators only; combining marks and pause signs remain verbatim.
    while end > start and text[end - 1].isspace():
        end -= 1
    return ResolvedSpan(span, text[start:end], f"{target_key[0]}:{target_key[1]}", start, end,
                        span.word_start == 1, span.word_end == record["word_count"])
