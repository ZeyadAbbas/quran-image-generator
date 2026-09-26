from copy import deepcopy

import pytest

from verse import Verse


def test_parses_verse_words(load_json_fixture, fake_font_metrics, layout_config):
    payload = load_json_fixture("verse_no_translations.json")

    verse = Verse(payload)

    assert verse.words == ["بِسْمِ", "اللَّهِ"]
    assert verse.number == 1


def test_parses_one_translation(load_json_fixture, fake_font_metrics, layout_config):
    payload = load_json_fixture("verse_one_translation.json")

    verse = Verse(payload)

    assert [translation.code for translation in verse.translations] == ["131"]
    assert verse.translations[0].words[:4] == ["In", "the", "Name", "of"]


def test_orders_multiple_translations_by_configuration(
    load_json_fixture, fake_font_metrics, layout_config
):
    payload = load_json_fixture("verse_multiple_translations.json")

    verse = Verse(payload)

    assert [translation.code for translation in verse.translations] == ["131", "31"]


@pytest.mark.xfail(
    strict=True,
    reason="Known translation bug tracked by #13: disabled translations use None",
)
def test_no_translations_are_an_empty_collection(
    load_json_fixture, fake_font_metrics, layout_config
):
    payload = load_json_fixture("verse_no_translations.json")

    assert Verse(payload).translations == []


@pytest.mark.xfail(
    strict=True,
    reason="Known normalization bug tracked by #9: parsing mutates the API payload",
)
def test_parsing_does_not_mutate_api_payload(
    load_json_fixture, fake_font_metrics, layout_config
):
    payload = load_json_fixture("verse_one_translation.json")
    original = deepcopy(payload)

    Verse(payload)

    assert payload == original
