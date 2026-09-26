from copy import deepcopy
from types import SimpleNamespace

import pytest

from quran_image_generator.content import (
    QuranApiConfig,
    QuranApiPayloadError,
    QuranContentClient,
    parse_verse,
)
from quran_image_generator.generator import QuranImageGenerator
from quran_image_generator.models import (
    GenerationRequest,
    TranslationResource,
    TranslationSelector,
)
from quran_image_generator.settings import TranslationSettings


class _FixtureSession:
    def __init__(self, content_for_url):
        self.content_for_url = content_for_url
        self.get_calls = []
        self.post_calls = []

    def post(self, uri, **kwargs):
        self.post_calls.append((uri, kwargs))
        return SimpleNamespace(
            status_code=200,
            headers={"Content-Type": "application/json"},
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
            headers={"Content-Type": "application/json"},
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
    payload["verse"]["translations"].append(
        {"resource_id": 31, "text": "second translation"}
    )
    session = _FixtureSession(lambda _uri: payload)
    client = _client(session)

    assert client.api_call("verses/by_key/1:1", ("131", "31")) == payload
    assert session.get_calls == [
        (
            ("https://apis-prelive.quran.foundation/content/api/v4/verses/by_key/1:1"),
            {
                "headers": {
                    "Accept": "application/json",
                    "x-auth-token": "fixture-token",
                    "x-client-id": "fixture-client",
                },
                "timeout": (5.0, 30.0),
                "params": {
                    "translations": "131,31",
                    "words": 1,
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

    passage = _client(session).fetch_passage(GenerationRequest(1, 1, 1), ("131",))

    assert [call[0] for call in session.get_calls] == [
        "https://apis-prelive.quran.foundation/content/api/v4/verses/by_key/1:1",
        "https://apis-prelive.quran.foundation/content/api/v4/chapters/1",
    ]
    assert session.get_calls[0][1]["params"] == {
        "translations": "131",
        "words": 1,
        "word_fields": "text_uthmani",
    }
    assert session.get_calls[1][1] == {
        "headers": {
            "Accept": "application/json",
            "x-auth-token": "fixture-token",
            "x-client-id": "fixture-client",
        },
        "timeout": (5.0, 30.0),
    }
    assert passage.chapter_name == "Al-Fatihah"
    assert [verse.key for verse in passage.verses] == ["1:1"]
    assert [
        translation.resource_id for translation in passage.verses[0].translations
    ] == ["131"]


def test_verse_without_translations_omits_translation_parameter(load_json_fixture):
    payload = load_json_fixture("verse_no_translations.json")
    session = _FixtureSession(lambda _uri: payload)

    assert _client(session).api_call("verses/by_key/1:1", ()) == payload
    assert session.get_calls[0][1]["params"] == {
        "words": 1,
        "word_fields": "text_uthmani",
    }


@pytest.mark.parametrize(
    ("payload", "resource_ids", "message"),
    [
        ({}, (), "verse object"),
        (
            {
                "verse": {
                    "verse_number": True,
                    "verse_key": "1:1",
                    "words": [],
                }
            },
            (),
            "verse_number",
        ),
        (
            {
                "verse": {
                    "verse_number": 1,
                    "verse_key": "",
                    "words": [],
                }
            },
            (),
            "verse_key",
        ),
        (
            {
                "verse": {
                    "verse_number": 1,
                    "verse_key": "1:1",
                    "words": "not-a-list",
                }
            },
            (),
            "words",
        ),
        (
            {
                "verse": {
                    "verse_number": 1,
                    "verse_key": "1:1",
                    "words": [{"char_type_name": "word"}],
                }
            },
            (),
            "include text",
        ),
        (
            {
                "verse": {
                    "verse_number": 1,
                    "verse_key": "1:1",
                    "words": [],
                    "translations": [{"resource_id": 131}],
                }
            },
            (),
            "translation text",
        ),
        (
            {
                "verse": {
                    "verse_number": 1,
                    "verse_key": "1:1",
                    "words": [],
                    "translations": [],
                }
            },
            ("131",),
            "requested translation",
        ),
    ],
)
def test_verse_response_fields_are_validated_before_mapping(
    payload, resource_ids, message
):
    session = _FixtureSession(lambda _uri: payload)

    with pytest.raises(QuranApiPayloadError, match=message):
        _client(session).api_call("verses/by_key/1:1", resource_ids)


@pytest.mark.parametrize(
    "payload",
    [{}, {"chapter": {}}, {"chapter": {"name_simple": ""}}],
)
def test_chapter_response_fields_are_validated_before_mapping(payload):
    session = _FixtureSession(lambda _uri: payload)

    with pytest.raises(QuranApiPayloadError, match="chapter|name_simple"):
        _client(session).api_call("chapters/1")


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


def test_unrequested_translation_resources_are_ignored(load_json_fixture):
    payload = load_json_fixture("verse_multiple_translations.json")

    verse = parse_verse(payload, ("131",))

    assert [translation.resource_id for translation in verse.translations] == ["131"]


def test_orders_three_translations_independently_of_api_order(load_json_fixture):
    payload = load_json_fixture("verse_multiple_translations.json")
    payload["verse"]["translations"].insert(
        1, {"resource_id": 83, "text": "En el nombre de Alá."}
    )

    verse = parse_verse(payload, ("131", "83", "31"))

    assert [translation.resource_id for translation in verse.translations] == [
        "131",
        "83",
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
                        '˹Read˺ <em>this</em>&nbsp;now<sup foot_note="42">42</sup>.'
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


@pytest.mark.parametrize(
    "translation_text",
    [
        pytest.param(" \t\n&nbsp; ", id="blank"),
        pytest.param(
            '<sup foot_note="42">suppressed footnote</sup>',
            id="markup-only",
        ),
    ],
)
def test_unreadable_requested_translation_stops_generation_before_output(
    translation_text,
    load_json_fixture,
    settings_factory,
):
    payload = load_json_fixture("verse_one_translation.json")
    payload["verse"]["translations"][0]["text"] = translation_text
    api_client = _client(_FixtureSession(lambda _uri: payload))
    resource = TranslationResource(
        "131",
        "clearquran-with-tafsir",
        "The Clear Quran",
        "Dr. Mustafa Khattab",
        "English",
        "en",
    )

    class ContentClient:
        def resolve_translations(self, selectors):
            return (resource,)

        def fetch_passage(self, request, resource_ids):
            return api_client.fetch_passage(request, resource_ids)

    class UnexpectedRenderer:
        def render(self, image_layout, settings, destination):
            pytest.fail("renderer must not run for an unreadable translation")

    def unexpected_layout(*args):
        pytest.fail("layout must not run for an unreadable translation")

    configured = TranslationSettings(TranslationSelector("id", "131"), None, 18)
    settings = settings_factory(translations=(configured,))
    generator = QuranImageGenerator(
        settings,
        ContentClient(),
        object(),
        UnexpectedRenderer(),
        image_opener=lambda path: pytest.fail("image opener must not run"),
        layout_builder=unexpected_layout,
    )

    with pytest.raises(QuranApiPayloadError, match="resource 131.*readable text"):
        generator.generate(GenerationRequest(1, 1, 1), open_output=True)

    assert list(settings.output_path.iterdir()) == []


def test_missing_requested_translation_fails_before_mapping(load_json_fixture):
    payload = load_json_fixture("verse_one_translation.json")
    session = _FixtureSession(lambda _uri: payload)

    with pytest.raises(QuranApiPayloadError, match="resource 31"):
        _client(session).api_call("verses/by_key/1:1", ("131", "31"))


def test_duplicate_requested_translation_fails_before_mapping(load_json_fixture):
    payload = load_json_fixture("verse_one_translation.json")
    payload["verse"]["translations"].append({"resource_id": 131, "text": "duplicate"})
    session = _FixtureSession(lambda _uri: payload)

    with pytest.raises(QuranApiPayloadError, match="resource 131 is duplicated"):
        _client(session).api_call("verses/by_key/1:1", ("131",))
