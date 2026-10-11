from copy import deepcopy
from dataclasses import asdict

import pytest
from test_api import fixture_request
from test_bindings import fixture_dataset
from test_content import CATALOG, FakeResponse, QueueSession, _chapter_one_translation

from quran_image_generator.api import execute_request
from quran_image_generator.content import QuranDataClient, TranslationTransportError
from quran_image_generator.references import CorpusIdentity
from quran_image_generator.snapshots import prepare_quranenc_snapshot


def source_request(tmp_path):
    return {"schema_version": 1, "request_id": "english-source", "operation": "prepare_translations",
            "source_corpus": asdict(CorpusIdentity()), "translation_resource": "english_saheeh",
            "snapshot_directory": str(tmp_path), "source_license": "provider terms",
            "source_attribution": "Noor International Center via QuranEnc",
            "cues": [{"cue_id": name, "spans": [{"surah": 1, "ayah": 2,
                       "word_start": 1, "word_end": end}]}
                     for name, end in [("first", 4), ("repeat", 4), ("partial", 2)]]}


def test_public_source_download_exact_repeats_partial_and_offline_pin(tmp_path, monkeypatch):
    session = QueueSession(FakeResponse(CATALOG), FakeResponse(_chapter_one_translation()),
                           FakeResponse(CATALOG))
    client = QuranDataClient(session=session)
    QuranDataClient.clear_translation_catalog_cache()

    def download(store, key, chapters, **kwargs):
        return prepare_quranenc_snapshot(store, key, chapters, client=client, **kwargs)

    monkeypatch.setattr("quran_image_generator.translation_api.prepare_quranenc_snapshot", download)
    request = source_request(tmp_path)
    response = execute_request(request).to_dict()
    assert response["status"] == "complete", response
    prepared = response["translation_preparation"]
    assert [c["status"] for c in prepared["cues"]] == ["bound", "bound", "needs_phrase_review"]
    assert prepared["cues"][0]["binding_id"] == prepared["cues"][1]["binding_id"]
    assert prepared["cues"][2]["binding_id"] is None
    bindings = prepared["dataset"]["bindings"]
    assert len(bindings) == 1 and bindings[0]["segments"] == [" english_saheeh verse 2 "]
    assert bindings[0]["review_status"] == "needs_review" and not bindings[0]["edited"]
    assert len(session.calls) == 3  # One chapter payload, catalog verified before and after.
    request["source_snapshot_sha256"] = prepared["source_snapshot"]["sha256"]
    monkeypatch.setattr("quran_image_generator.translation_api.prepare_quranenc_snapshot",
                        lambda *a, **k: pytest.fail("Pinned offline preparation must not fetch"))
    assert execute_request(request).to_dict()["translation_preparation"] == prepared
    wrong = {**request, "translation_resource": "other_edition"}
    assert execute_request(wrong).to_dict()["error"]["code"] == "stale_translation"
    path = tmp_path / f"{request['source_snapshot_sha256']}.json"
    path.write_text("{}", "utf-8")
    assert execute_request(request).to_dict()["error"]["code"] == "corrupt_snapshot"


def test_provider_failure_is_typed_and_retryable(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise TranslationTransportError("provider offline")

    monkeypatch.setattr("quran_image_generator.translation_api.prepare_quranenc_snapshot", fail)
    result = execute_request(source_request(tmp_path)).to_dict()
    assert result["status"] == "failed"
    assert result["error"]["code"] == "translation_unavailable" and result["error"]["retryable"]


def test_draft_english_is_explicit_and_does_not_approve_production(tmp_path):
    request = fixture_request(tmp_path, "layout")
    dataset = deepcopy(fixture_dataset().to_dict())
    dataset["bindings"][0].update(review_status="needs_review", reviewer="")
    request["translation_dataset"] = dataset
    for cue in request["cues"]:
        cue.update(translation_policy="review", translation_binding_id="31-9-prefix")
    first = execute_request(request).to_dict()
    assert len(first["cues"][0]["layers"]) == 1  # Existing behavior stays explicit.
    for cue in request["cues"]:
        cue["preview_unreviewed_translation"] = True
    preview = execute_request(request).to_dict()
    assert preview["status"] == "needs_review" and len(preview["cues"][0]["layers"]) == 2
    assert preview["cues"][0]["translation"]["binding"]["review_status"] == "needs_review"
    for cue in request["cues"]:
        cue["translation_policy"] = "required"
    failed = execute_request(request).to_dict()
    assert failed["status"] == "failed"
    assert failed["cues"][0]["error"]["code"] == "translation_review"


def test_catalog_filter_is_public_and_missing_fields_fail_before_network(monkeypatch, tmp_path):
    session = QueueSession(FakeResponse(CATALOG))
    client = QuranDataClient(session=session)
    monkeypatch.setattr("quran_image_generator.translation_api.QuranDataClient", lambda **_: client)
    result = execute_request({"schema_version": 1, "request_id": "catalog",
                              "operation": "translation_catalog", "translation_language": "en"})
    assert len(result.to_dict()["translation_catalog"]) == 2
    request = source_request(tmp_path)
    del request["translation_resource"]
    assert execute_request(request).to_dict()["error"]["code"] == "invalid_request"
    assert len(session.calls) == 1
