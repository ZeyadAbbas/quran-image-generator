import pytest

import read_config as config
from translation import Translation
from verse import Verse


def test_verse_wrapping_and_height_are_deterministic(
    monkeypatch, fake_font_metrics, layout_config
):
    monkeypatch.setattr(config, "quran_max_width", lambda: 35)
    payload = {
        "verse": {
            "verse_number": 1,
            "words": [
                {"char_type_name": "word", "text": "aaa"},
                {"char_type_name": "word", "text": "bb"},
                {"char_type_name": "end", "text": "1"},
            ],
        }
    }

    verse = Verse(payload)

    assert [(line.text, line.width, line.height) for line in verse.lines] == [
        ("aaa", 30, 12),
        ("bb", 20, 12),
    ]
    assert verse.height == 29


def test_translation_wrapping_and_height_are_deterministic(
    monkeypatch, fake_font_metrics, layout_config
):
    monkeypatch.setattr(config, "translation_max_width", lambda: 65)

    translation = Translation({"resource_id": 131, "text": "first second"})

    assert [line.text for line in translation.lines] == ["first", "second"]
    assert translation.height == 34


@pytest.mark.xfail(
    strict=True,
    reason="Known wrapping bug tracked by #9: an oversized first token emits an empty line",
)
def test_oversized_first_word_does_not_create_an_empty_line(
    monkeypatch, fake_font_metrics, layout_config
):
    monkeypatch.setattr(config, "quran_max_width", lambda: 30)
    payload = {
        "verse": {
            "verse_number": 1,
            "words": [
                {"char_type_name": "word", "text": "oversized"},
                {"char_type_name": "end", "text": "1"},
            ],
        }
    }

    verse = Verse(payload)

    assert all(line.text for line in verse.lines)
