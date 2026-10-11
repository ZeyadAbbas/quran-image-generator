"""Explicit provider retrieval before rendering; exact whole-ayah draft bindings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .bindings import BindingDataset, PhraseBinding, TranslationSource, text_hash
from .content import QuranDataClient, QuranDataError, TranslationTransportError
from .excerpts import ExcerptRequest, select_excerpt
from .references import CorpusIdentity, ReferenceError, SourceSpan
from .snapshots import SnapshotStore, prepare_quranenc_snapshot


def translation_catalog(language: str | None = None) -> list[dict[str, Any]]:
    try:
        catalog = QuranDataClient(timeout=5, max_attempts=2).translation_catalog(refresh=True)
        return [asdict(r) for r in catalog.resources
                if language is None or r.language_code == language]
    except QuranDataError as error:
        raise _provider_error(error) from error


def _provider_error(error: QuranDataError) -> ReferenceError:
    return ReferenceError("translation_unavailable" if isinstance(error, TranslationTransportError)
                          else "invalid_translation_source", str(error))


def prepare_translation_source(
    data: dict[str, Any], root: Path, *, deadline_seconds: float | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    corpus = CorpusIdentity(**data["source_corpus"])
    corpus.validate()
    resolved = []
    chapters: set[int] = set()
    for cue in data["cues"]:
        spans = tuple(SourceSpan(**s) for s in cue["spans"])
        excerpt = select_excerpt(ExcerptRequest(cue["cue_id"], spans, corpus))
        chapters.update(s.surah or 1 for s in spans)
        resolved.append((cue, spans, excerpt))
    directory = (root / data["snapshot_directory"]).resolve()
    store = SnapshotStore(directory)
    if cancelled and cancelled():
        raise ReferenceError("cancelled", "Translation preparation cancelled")
    digest = data.get("source_snapshot_sha256")
    if digest is None:
        try:
            digest = prepare_quranenc_snapshot(
                store, data["translation_resource"], tuple(sorted(chapters)),
                license=data["source_license"], attribution=data["source_attribution"],
                deadline_seconds=min(120, deadline_seconds or data.get("deadline_seconds", 120)))
        except QuranDataError as error:
            raise _provider_error(error) from error
    if cancelled and cancelled():
        raise ReferenceError("cancelled", "Translation preparation cancelled")
    payload = store.read(digest)
    if (payload.get("kind") != "whole_ayah_translation" or payload.get("schema_version") != 1
            or payload["source"]["resource_id"] != data["translation_resource"]
            or not chapters.issubset(payload["chapters"])
            or payload["source"]["license"] != data["source_license"]
            or payload["source"]["attribution"] != data["source_attribution"]):
        raise ReferenceError("stale_translation", "Pinned source differs from the selected edition")
    resource = payload["source"]
    source = TranslationSource(
        provider=resource["provider"], resource=resource["resource_id"],
        version=resource["version"], translator=resource["description"] or resource["name"],
        license=resource["license"], attribution=resource["attribution"],
        direction=resource["direction"])
    bindings: dict[str, PhraseBinding] = {}
    cues = []
    for cue, spans, excerpt in resolved:
        # Only complete ayahs can mechanically bind a provider's whole-ayah wording.
        full = all(s.starts_ayah and s.ends_ayah for s in excerpt.spans)
        binding_id = None
        if full:
            text = "\n".join(payload["verses"][s.target_verse] for s in excerpt.spans)
            if any(c in text for c in "<>\x00"):
                raise ReferenceError("invalid_translation_source", "Provider returned non-plain text")
            binding_id = "source-" + text_hash(str(asdict(source)) + str(cue["spans"]))[:32]
            bindings[binding_id] = PhraseBinding(
                binding_id, "1", spans, text_hash(excerpt.text), text, text_hash(text),
                tuple(text.splitlines()), "needs_review", "", False,
                source_identity_sha256=source.identity_sha256)
        cues.append({"cue_id": cue["cue_id"], "spans": cue["spans"],
                     "binding_id": binding_id,
                     "status": "bound" if full else "needs_phrase_review"})
    dataset = BindingDataset(source, corpus, tuple(bindings.values())).to_dict()
    return {"dataset": dataset, "source_snapshot": {"directory": str(directory), "sha256": digest},
            "cues": cues}
