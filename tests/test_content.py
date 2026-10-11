from __future__ import annotations

from copy import deepcopy

import pytest
import requests

from quran_image_generator import content
from quran_image_generator.content import (
    QuranDataClient,
    QuranDataIntegrityError,
    TranslationHttpError,
    TranslationPayloadError,
    TranslationSelectionError,
    TranslationTransportError,
)
from quran_image_generator.models import GenerationRequest, TranslationSelector


class FakeResponse:
    def __init__(self, payload, status_code=200, *, json_error=None):
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return deepcopy(self.payload)


class QueueSession:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.results:
            pytest.fail(f"unexpected HTTP request: {url}")
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


CATALOG = {
    "translations": [
        {
            "key": "english_saheeh",
            "direction": "ltr",
            "language_iso_code": "en",
            "version": "1.1.2",
            "title": "English Translation - Noor International Center",
            "description": "Issued by Noor International Center.",
        },
        {
            "key": "english_demo",
            "direction": "ltr",
            "language_iso_code": "en",
            "version": "2.0.0",
            "title": "Another English Translation",
            "description": "A second English translator.",
        },
        {
            "key": "french_montada",
            "direction": "ltr",
            "language_iso_code": "fr",
            "version": "1.0.0",
            "title": "Traduction française",
            "description": "Association Montada.",
        },
    ]
}


def _chapter_one_translation(key="english_saheeh"):
    return {
        "result": [
            {
                "id": str(number),
                "sura": "1",
                "aya": str(number),
                "arabic_text": "ignored in favor of bundled text",
                "translation": f" {key} verse {number} ",
                "footnotes": "",
            }
            for number in range(1, 8)
        ]
    }


def test_bundled_catalog_is_complete_and_requires_no_network():
    session = QueueSession()
    chapters = QuranDataClient(session=session).list_chapters()

    assert len(chapters) == 114
    assert sum(item.verses_count for item in chapters) == 6236
    assert chapters[0].number == 1
    assert chapters[0].name_simple == "Al-Faatiha"
    assert chapters[0].verses_count == 7
    assert chapters[-1].number == 114
    assert chapters[-1].verses_count == 6
    assert session.calls == []


def test_arabic_passage_is_loaded_offline_from_tanzil():
    session = QueueSession()
    passage = QuranDataClient(session=session).fetch_passage(
        GenerationRequest(1, 1, 2), ()
    )

    assert passage.chapter.name_simple == "Al-Faatiha"
    assert passage.verses[0].key == "1:1"
    assert " ".join(passage.verses[0].words) == (
        "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ"
    )
    assert passage.verses[1].number == 2
    assert passage.verses[0].translations == ()
    assert session.calls == []


def test_bundled_text_hash_rejects_modified_content(monkeypatch):
    original_reader = content._package_bytes

    def changed_reader(path):
        data = original_reader(path)
        return data + b"changed" if path == content.TANZIL_TEXT_PATH else data

    monkeypatch.setattr(content, "_package_bytes", changed_reader)
    content._load_bundled_corpus.cache_clear()

    with pytest.raises(QuranDataIntegrityError, match="SHA-256"):
        QuranDataClient().list_chapters()


def test_catalog_maps_quranenc_fields_and_languages():
    session = QueueSession(FakeResponse(CATALOG))
    catalog = QuranDataClient(session=session).translation_catalog()

    by_key = {item.resource_id: item for item in catalog.resources}
    assert by_key["english_saheeh"].version == "1.1.2"
    assert by_key["english_saheeh"].language_code == "en"
    assert by_key["french_montada"].name == "Traduction française"
    assert [(item.iso_code, item.translations_count) for item in catalog.languages] == [
        ("en", 2),
        ("fr", 1),
    ]
    assert session.calls == [
        (
            "https://quranenc.com/api/v1/translations/list?localization=en",
            {"timeout": 20.0},
        )
    ]


def test_catalog_is_cached_until_refresh():
    session = QueueSession(FakeResponse(CATALOG), FakeResponse(CATALOG))
    client = QuranDataClient(session=session)

    assert client.translation_catalog() is client.translation_catalog()
    client.translation_catalog(refresh=True)

    assert len(session.calls) == 2


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "must be an object"),
        ({}, "translations list"),
        ({"translations": []}, "empty"),
        (
            {"translations": [CATALOG["translations"][0], CATALOG["translations"][0]]},
            "duplicated",
        ),
        (
            {"translations": [{**CATALOG["translations"][0], "direction": "down"}]},
            "direction",
        ),
    ],
)
def test_catalog_rejects_invalid_payloads(payload, message):
    with pytest.raises(TranslationPayloadError, match=message):
        QuranDataClient(session=QueueSession(FakeResponse(payload))).translation_catalog()


def test_translation_selectors_use_exact_keys_and_strict_languages():
    client = QuranDataClient(session=QueueSession(FakeResponse(CATALOG)))

    selected = client.resolve_translations(
        (
            TranslationSelector("key", "ENGLISH_SAHEEH"),
            TranslationSelector("language", "fr"),
        )
    )
    assert [item.resource_id for item in selected] == [
        "english_saheeh",
        "french_montada",
    ]

    with pytest.raises(TranslationSelectionError, match="multiple"):
        client.resolve_translations((TranslationSelector("language", "en"),))
    with pytest.raises(TranslationSelectionError, match="no translation"):
        client.resolve_translations((TranslationSelector("key", "missing"),))
    with pytest.raises(TranslationSelectionError, match="already selected"):
        client.resolve_translations(
            (
                TranslationSelector("key", "english_saheeh"),
                TranslationSelector("key", "ENGLISH_SAHEEH"),
            )
        )


def test_fetch_passage_uses_bundled_arabic_and_quranenc_translation():
    session = QueueSession(FakeResponse(_chapter_one_translation()))
    passage = QuranDataClient(session=session).fetch_passage(
        GenerationRequest(1, 2, 3), ("english_saheeh",)
    )

    assert [item.key for item in passage.verses] == ["1:2", "1:3"]
    assert passage.verses[0].translations[0].resource_id == "english_saheeh"
    assert passage.verses[0].translations[0].text == " english_saheeh verse 2 "
    assert "ٱلْحَمْدُ" in passage.verses[0].words
    assert session.calls[0][0].endswith("/translation/sura/english_saheeh/1")


def test_full_translation_chapter_is_cached_for_later_ranges():
    session = QueueSession(FakeResponse(_chapter_one_translation()))
    client = QuranDataClient(session=session)

    client.fetch_passage(GenerationRequest(1, 1, 1), ("english_saheeh",))
    client.fetch_passage(GenerationRequest(1, 7, 7), ("english_saheeh",))

    assert len(session.calls) == 1


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "result list"),
        ({"result": []}, "every verse"),
        (
            {
                "result": [
                    {
                        "sura": "2",
                        "aya": "1",
                        "translation": "wrong chapter",
                    }
                ]
            },
            "does not identify",
        ),
        (
            {
                "result": [
                    {"sura": "1", "aya": "1", "translation": " "}
                ]
            },
            "no text",
        ),
    ],
)
def test_translation_response_rejects_incomplete_or_invalid_content(payload, message):
    with pytest.raises(TranslationPayloadError, match=message):
        QuranDataClient(session=QueueSession(FakeResponse(payload))).fetch_passage(
            GenerationRequest(1, 1, 1), ("english_saheeh",)
        )


def test_transient_transport_failure_is_retried_with_bounded_backoff():
    delays = []
    session = QueueSession(
        requests.ConnectionError("offline"),
        FakeResponse(CATALOG),
    )
    catalog = QuranDataClient(session=session, sleep=delays.append).translation_catalog()

    assert catalog.resources
    assert delays == [1.0]
    assert len(session.calls) == 2


def test_transport_failure_does_not_expose_low_level_exception():
    session = QueueSession(
        requests.ConnectionError("private network details"),
        requests.ConnectionError("private network details"),
    )
    with pytest.raises(TranslationTransportError, match="after 2 attempts") as caught:
        QuranDataClient(session=session, max_attempts=2, sleep=lambda _: None).translation_catalog()
    assert "private network details" not in str(caught.value)


def test_http_failure_and_invalid_json_are_reported_safely():
    with pytest.raises(TranslationHttpError, match="HTTP 404"):
        QuranDataClient(session=QueueSession(FakeResponse({}, 404))).translation_catalog()

    with pytest.raises(TranslationPayloadError, match="invalid JSON"):
        QuranDataClient(
            session=QueueSession(FakeResponse({}, json_error=ValueError("broken")))
        ).translation_catalog()


@pytest.mark.parametrize(
    "kwargs",
    ({"timeout": 0}, {"max_attempts": 0}),
)
def test_client_rejects_invalid_retry_configuration(kwargs):
    with pytest.raises(ValueError):
        QuranDataClient(**kwargs)
