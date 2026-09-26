from copy import deepcopy
from types import SimpleNamespace

import pytest

from quran_image_generator.content import (
    QuranApiConfig,
    QuranContentClient,
    parse_verse,
)
from quran_image_generator.models import GenerationRequest


class _FixtureSession:
    def __init__(self, content_for_url):
        self.content_for_url = content_for_url
        self.get_calls = []
        self.post_calls = []

    def post(self, uri, **kwargs):
        self.post_calls.append((uri, kwargs))
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "access_token": "fixture-token",
                "token_type": "bearer",
                "expires_in": 3600,
            },
        )

    def get(self, uri, **kwargs):
        self.get_calls.append((uri, kwargs))
        return SimpleNamespace(
            status_code=200,
            json=lambda: self.content_for_url(uri),
        )


def _client(session):
    return QuranContentClient(
        QuranApiConfig("prelive", "fixture-client", "fixture-secret"),
        session=session,
        monotonic=lambda: 0.0,
    )


def test_api_call_builds_expected_request(load_json_fixture):
    payload = load_json_fixture("verse_one_translation.json")
    session = _FixtureSession(lambda _uri: payload)
    client = _client(session)

    assert client.api_call("verses/by_key/1:1", ("131", "31")) == payload
    assert session.get_calls == [
        (
            (
                "https://apis-prelive.quran.foundation/content/api/v4/"
                "verses/by_key/1:1"
            ),
            {
                "headers": {
                    "Accept": "application/json",
                    "x-auth-token": "fixture-token",
                    "x-client-id": "fixture-client",
                },
                "timeout": 30,
                "params": {
                    "translations": "131,31",
                    "words": True,
                    "word_fields": "text_uthmani",
                },
            },
        )
    ]


def test_fetch_passage_gets_verses_then_chapter(load_json_fixture):
    verse_payload = load_json_fixture("verse_one_translation.json")
    chapter_payload = load_json_fixture("chapter.json")
    session = _FixtureSession(
        lambda uri: chapter_payload if uri.endswith("chapters/1") else verse_payload
    )

    passage = _client(session).fetch_passage(
        GenerationRequest(1, 1, 1), ("131",)
    )

    assert [call[0] for call in session.get_calls] == [
        "https://apis-prelive.quran.foundation/content/api/v4/verses/by_key/1:1",
        "https://apis-prelive.quran.foundation/content/api/v4/chapters/1",
    ]
    assert session.get_calls[0][1]["params"] == {
        "translations": "131",
        "words": True,
        "word_fields": "text_uthmani",
    }
    assert session.get_calls[1][1] == {
        "headers": {
            "Accept": "application/json",
            "x-auth-token": "fixture-token",
            "x-client-id": "fixture-client",
        },
        "timeout": 30,
    }
    assert passage.chapter_name == "Al-Fatihah"
    assert [verse.key for verse in passage.verses] == ["1:1"]
    assert [
        translation.resource_id
        for translation in passage.verses[0].translations
    ] == ["131"]


def test_verse_without_translations_omits_translation_parameter(load_json_fixture):
    payload = load_json_fixture("verse_no_translations.json")
    session = _FixtureSession(lambda _uri: payload)

    assert _client(session).api_call("verses/by_key/1:1", ()) == payload
    assert session.get_calls[0][1]["params"] == {
        "words": True,
        "word_fields": "text_uthmani",
    }


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


def test_final_word_is_kept_when_no_end_token_is_present():
    payload = {
        "verse": {
            "verse_number": 1,
            "verse_key": "1:1",
            "words": [
                {"char_type_name": "word", "text": "first"},
                {"char_type_name": "word", "text": "last"},
            ],
        }
    }

    assert parse_verse(payload, ()).words == ("first", "last")


def test_official_uthmani_word_field_is_preferred_with_legacy_fallback():
    payload = {
        "verse": {
            "verse_number": 1,
            "verse_key": "1:1",
            "words": [
                {
                    "char_type_name": "word",
                    "text_uthmani": "official",
                    "text": "legacy",
                },
                {"char_type_name": "word", "text": "fallback"},
                {"char_type_name": "end", "text_uthmani": "1"},
            ],
        }
    }

    assert parse_verse(payload, ()).words == ("official", "fallback")


def test_null_and_blank_uthmani_values_use_legacy_text():
    payload = {
        "verse": {
            "verse_number": 1,
            "verse_key": "1:1",
            "words": [
                {
                    "char_type_name": "word",
                    "text_uthmani": None,
                    "text": "legacy",
                },
                {
                    "char_type_name": "word",
                    "text_uthmani": "",
                    "text": "fallback",
                },
            ],
        }
    }

    assert parse_verse(payload, ()).words == ("legacy", "fallback")


def test_translation_markup_preserves_readable_text_and_removes_footnote():
    payload = {
        "verse": {
            "verse_number": 1,
            "verse_key": "1:1",
            "words": [],
            "translations": [
                {
                    "resource_id": 131,
                    "text": (
                        "˹Read˺ <em>this</em>&nbsp;now"
                        '<sup foot_note="42">42</sup>.'
                    ),
                }
            ],
        }
    }

    verse = parse_verse(payload, ("131",))

    assert verse.translations[0].text == "Read this now."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "before <sup foot_note=1>hidden<wbr>note</sup> after",
            "before after",
        ),
        ("2<sup>nd</sup> place", "2nd place"),
        (
            "before <sup footnote=1>hidden</em>still hidden</sup> after",
            "before after",
        ),
    ],
)
def test_translation_footnote_suppression_is_tag_aware(text, expected):
    payload = {
        "verse": {
            "verse_number": 1,
            "verse_key": "1:1",
            "words": [],
            "translations": [{"resource_id": 131, "text": text}],
        }
    }

    verse = parse_verse(payload, ("131",))

    assert verse.translations[0].text == expected


@pytest.mark.xfail(
    strict=True,
    reason="Known missing-resource behavior tracked by #13",
)
def test_missing_requested_translation_is_skipped(load_json_fixture):
    payload = load_json_fixture("verse_one_translation.json")

    verse = parse_verse(payload, ("131", "31"))

    assert [translation.resource_id for translation in verse.translations] == ["131"]
