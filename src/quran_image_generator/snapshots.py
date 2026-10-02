"""Content-addressed immutable offline snapshots with atomic publication."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .bindings import BindingDataset
from .content import QuranDataClient
from .models import GenerationRequest, TranslationSelector
from .references import ReferenceError


def canonical_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


class SnapshotStore:
    """Writes only on explicit prepare/import. Reading never contacts a provider."""
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()

    def put(self, payload: dict[str, Any]) -> str:
        raw = canonical_bytes(payload)
        if len(raw) > 8_000_000:
            raise ReferenceError("invalid_translation", "Snapshot exceeds 8 MB")
        digest = hashlib.sha256(raw).hexdigest()
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f"{digest}.json"
        if target.exists():
            self.read(digest)
            return digest
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, suffix=".tmp", delete=False) as stream:
                temporary = stream.name
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
        self.read(digest)
        return digest

    def read(self, digest: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ReferenceError("invalid_translation", "Snapshot ID must be a SHA-256")
        path = self.directory / f"{digest}.json"
        try:
            if path.stat().st_size > 8_000_000:
                raise ReferenceError("corrupt_snapshot", "Snapshot exceeds 8 MB")
            raw = path.read_bytes()
        except FileNotFoundError as error:
            raise ReferenceError("offline_translation_miss", "Pinned snapshot is unavailable offline; explicitly prepare/import it") from error
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ReferenceError("corrupt_snapshot", "Pinned snapshot failed its checksum")
        result: dict[str, Any] = json.loads(raw)
        return result

    def import_dataset(self, dataset: BindingDataset) -> str:
        return self.put({"kind": "phrase_bindings", "schema_version": 1, "dataset": dataset.to_dict()})

    def bindings(self, digest: str) -> BindingDataset:
        payload = self.read(digest)
        if payload.get("kind") != "phrase_bindings" or payload.get("schema_version") != 1:
            raise ReferenceError("invalid_translation", "Expected a version 1 phrase-binding snapshot")
        return BindingDataset.from_dict(payload["dataset"])


def prepare_quranenc_snapshot(store: SnapshotStore, resource_key: str, chapters: tuple[int, ...], *,
                             license: str, attribution: str, client: QuranDataClient | None = None,
                             deadline_seconds: float = 120) -> str:
    """Explicit download. Whole-ayah sources still require reviewed phrase binding."""
    if not license.strip() or not attribution.strip() or not chapters or len(chapters) > 114 or deadline_seconds <= 0:
        raise ReferenceError("invalid_translation", "Supply chapters, attribution, license and a positive deadline")
    provider = client or QuranDataClient(timeout=5, max_attempts=2)
    deadline = time.monotonic() + deadline_seconds
    provider.translation_catalog(refresh=True)
    resource = provider.resolve_translations((TranslationSelector("key", resource_key),))[0]
    text: dict[str, str] = {}
    for chapter_number in dict.fromkeys(chapters):
        if time.monotonic() >= deadline:
            raise ReferenceError("translation_deadline", "Snapshot download deadline exceeded")
        chapter = provider.get_chapter(chapter_number)
        passage = provider.fetch_passage(GenerationRequest(chapter_number, 1, chapter.verses_count), (resource.resource_id,))
        text.update({verse.key: verse.translations[0].text for verse in passage.verses})
    latest = provider.resolve_translations((TranslationSelector("key", resource_key),), refresh=True)[0]
    if latest != resource:
        raise ReferenceError("stale_translation", "Provider catalog changed during download; retry explicitly")
    if time.monotonic() >= deadline:
        raise ReferenceError("translation_deadline", "Snapshot download deadline exceeded")
    return store.put({"kind": "whole_ayah_translation", "schema_version": 1,
                      "source": {"provider": "QuranEnc", **asdict(resource), "license": license, "attribution": attribution},
                      "chapters": sorted(set(chapters)), "verses": text})
