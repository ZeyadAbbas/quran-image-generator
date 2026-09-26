import pytest

from layout import build_layout, layout_quran_text, layout_translation_text
from models import Passage, Verse, VerseTranslation
from settings import TranslationSettings


def test_verse_wrapping_and_height_are_deterministic(
    fake_measurer, settings_factory
):
    settings = settings_factory(quran_max_width=35)

    block = layout_quran_text(("aaa", "bb"), settings, fake_measurer)

    assert [(line.text, line.width, line.height) for line in block.lines] == [
        ("aaa", 30, 12),
        ("bb", 20, 12),
    ]
    assert block.height == 29


def test_translation_wrapping_and_height_are_deterministic(
    fake_measurer, settings_factory
):
    translations = (
        TranslationSettings("en", "131", "Fixture Sans", 18),
    )
    settings = settings_factory(
        translations=translations,
        translation_max_width=65,
    )

    block = layout_translation_text(
        VerseTranslation("131", "first second"), settings, fake_measurer
    )

    assert [line.text for line in block.lines] == ["first", "second"]
    assert block.height == 34


def test_translation_uses_legacy_markup_and_delimiter_normalization(
    fake_measurer, settings_factory
):
    translations = (
        TranslationSettings("en", "131", "Fixture Sans", 18),
    )
    settings = settings_factory(translations=translations)

    block = layout_translation_text(
        VerseTranslation(
            "131",
            "Keep <sup foot_note=1>remove</sup> ˹these˺\xa0words",
        ),
        settings,
        fake_measurer,
    )

    assert [line.text for line in block.lines] == ["Keep these words"]


def test_build_layout_preserves_centering_and_baseline(settings_factory):
    class FixedMeasurer:
        def measure(self, text, style):
            return 30, 10

    passage = Passage(
        1,
        "Al-Fatihah",
        (Verse(1, "1:1", ("بِسْمِ",), ()),),
    )

    image_layout = build_layout(passage, settings_factory(), FixedMeasurer())

    assert image_layout.content_height == 10
    assert [(int(line.x), int(line.y), line.text) for line in image_layout.lines] == [
        (135, 105, "بِسْمِ")
    ]


@pytest.mark.xfail(
    strict=True,
    reason="Known wrapping bug tracked by #9: an oversized first token emits an empty line",
)
def test_oversized_first_word_does_not_create_an_empty_line(
    fake_measurer, settings_factory
):
    settings = settings_factory(quran_max_width=30)

    block = layout_quran_text(("oversized",), settings, fake_measurer)

    assert all(line.text for line in block.lines)
