from copy import deepcopy
from types import SimpleNamespace

import pytest

from content import QuranContentClient, parse_verse
from models import GenerationRequest


def test_api_call_builds_expected_request(load_json_fixture):
    payload = load_json_fixture("verse_one_translation.json")
    captured = {}

    def fake_get(uri, **kwargs):
        captured["uri"] = uri
        captured.update(kwargs)
        return SimpleNamespace(json=lambda: payload)

    client = QuranContentClient(http_get=fake_get)

    assert client.api_call("verses/by_key/1:1", ("131", "31")) == payload
    assert captured == {
        "uri": "https://api.quran.com/api/v4/verses/by_key/1:1",
        "headers": {"Accept": "application/json"},
        "data": {},
        "params": {
            "translations": "131, 31",
            "words": 1,
            "word_fields": "text_uthmani",
        },
    }


def test_fetch_passage_gets_verses_then_chapter(load_json_fixture):
    verse_payload = load_json_fixture("verse_one_translation.json")
    chapter_payload = load_json_fixture("chapter.json")
    requests = []

    def fake_get(uri, **kwargs):
        requests.append((uri, kwargs["params"]["translations"]))
        payload = chapter_payload if uri.endswith("chapters/1") else verse_payload
        return SimpleNamespace(json=lambda: payload)

    passage = QuranContentClient(http_get=fake_get).fetch_passage(
        GenerationRequest(1, 1, 1), ("131",)
    )

    assert requests == [
        ("https://api.quran.com/api/v4/verses/by_key/1:1", "131"),
        ("https://api.quran.com/api/v4/chapters/1", "131"),
    ]
    assert passage.chapter_name == "Al-Fatihah"
    assert [verse.key for verse in passage.verses] == ["1:1"]
    assert [
        translation.resource_id
        for translation in passage.verses[0].translations
    ] == ["131"]


def test_parses_verse_words(load_json_fixture):
    payload = load_json_fixture("verse_no_translations.json")

    verse = parse_verse(payload, ())

    assert verse.words == ("بِسْمِ", "اللَّهِ")
    assert verse.number == 1
    assert verse.key == "1:1"


def test_parses_one_translation(load_json_fixture):
    payload = load_json_fixture("verse_one_translation.json")

    verse = parse_verse(payload, ("131",))

    assert [translation.resource_id for translation in verse.translations] == ["131"]
    assert verse.translations[0].text.startswith("In the Name of")


def test_orders_multiple_translations_by_configuration(load_json_fixture):
    payload = load_json_fixture("verse_multiple_translations.json")

    verse = parse_verse(payload, ("131", "31"))

    assert [translation.resource_id for translation in verse.translations] == [
        "131",
        "31",
    ]


def test_no_translations_are_an_empty_collection(load_json_fixture):
    payload = load_json_fixture("verse_no_translations.json")

    assert parse_verse(payload, ()).translations == ()


def test_parsing_does_not_mutate_api_payload(load_json_fixture):
    payload = load_json_fixture("verse_one_translation.json")
    original = deepcopy(payload)

    parse_verse(payload, ("131",))

    assert payload == original


@pytest.mark.xfail(
    strict=True,
    reason="Known token filtering bug tracked by #9: the final item is dropped blindly",
)
def test_only_declared_end_tokens_are_removed():
    payload = {
        "verse": {
            "verse_number": 1,
            "verse_key": "1:1",
            "words": [
                {"char_type_name": "word", "text": "first"},
                {"char_type_name": "end", "text": "1"},
                {"char_type_name": "word", "text": "last"},
            ],
        }
    }

    assert parse_verse(payload, ()).words == ("first", "last")


@pytest.mark.xfail(
    strict=True,
    reason="Known missing-resource behavior tracked by #13",
)
def test_missing_requested_translation_is_skipped(load_json_fixture):
    payload = load_json_fixture("verse_one_translation.json")

    verse = parse_verse(payload, ("131", "31"))

    assert [translation.resource_id for translation in verse.translations] == ["131"]
