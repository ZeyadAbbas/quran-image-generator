import pytest

from quran_image_generator.layout import (
    LayoutOverflowError,
    TextMetrics,
    build_layout,
    layout_quran_text,
    layout_translation_text,
)
from quran_image_generator.models import (
    Passage,
    TranslationResource,
    TranslationSelector,
    Verse,
    VerseTranslation,
)
from quran_image_generator.settings import Dimensions, TranslationSettings


class FixedMeasurer:
    def __init__(
        self,
        width,
        height,
        descender=0,
        ascender=None,
        left_offset=0,
        right_offset=None,
    ):
        self.width = width
        self.height = height
        self.ascender = height if ascender is None else ascender
        self.descender = descender
        self.left_offset = left_offset
        self.right_offset = right_offset

    def measure(self, text, style):
        return TextMetrics(
            self.width,
            self.height,
            self.ascender,
            self.descender,
            left_offset=self.left_offset,
            right_offset=self.right_offset,
        )


def passage_with(*verses):
    return Passage(1, "Al-Fatihah", tuple(verses))


def resolved_translation(resource_id, language_code="en"):
    resource = TranslationResource(
        resource_id,
        f"fixture-{resource_id}",
        f"Fixture {resource_id}",
        "Fixture Author",
        language_code,
        language_code,
    )
    return TranslationSettings(
        TranslationSelector("id", resource_id),
        "Fixture Sans",
        18,
        resource,
    )


def test_verse_wrapping_and_height_are_deterministic(fake_measurer, settings_factory):
    settings = settings_factory(quran_max_width=35)

    block = layout_quran_text(("aaa", "bb"), settings, fake_measurer)

    assert [(line.text, line.width, line.height) for line in block.lines] == [
        ("aaa", 30, 12),
        ("bb", 20, 12),
    ]
    assert block.height == 29


def test_translation_height_contains_only_interline_spacing(
    fake_measurer, settings_factory
):
    translations = (resolved_translation("131"),)
    settings = settings_factory(
        translations=translations,
        translation_max_width=65,
    )

    block = layout_translation_text(
        VerseTranslation("131", "first second"), settings, fake_measurer
    )

    assert [line.text for line in block.lines] == ["first", "second"]
    assert block.height == 27


def test_text_equal_to_maximum_width_stays_on_one_line(fake_measurer, settings_factory):
    settings = settings_factory(quran_max_width=50)

    block = layout_quran_text(("aa", "bb"), settings, fake_measurer)

    assert [(line.text, line.width) for line in block.lines] == [("aa bb", 50)]


def test_oversized_first_token_is_preserved_and_reported(
    fake_measurer, settings_factory
):
    settings = settings_factory(quran_max_width=30)
    verse = Verse(1, "1:1", ("oversized",), ())

    block = layout_quran_text(verse.words, settings, fake_measurer)

    assert [line.text for line in block.lines] == ["oversized"]
    with pytest.raises(LayoutOverflowError) as caught:
        build_layout(passage_with(verse), settings, fake_measurer)

    assert caught.value.element == "Quran text for verse 1:1 line 1"
    assert caught.value.axis == "horizontal"
    assert caught.value.actual == (0, 90)
    assert caught.value.allowed == (0, 30)
    assert caught.value.overflow == 60


def test_oversized_translation_token_does_not_drop_accumulated_text(
    fake_measurer, settings_factory
):
    translations = (resolved_translation("131"),)
    settings = settings_factory(
        translations=translations,
        translation_max_width=60,
    )
    source = "short " + ("x" * 71)

    block = layout_translation_text(
        VerseTranslation("131", source), settings, fake_measurer
    )

    assert [line.text for line in block.lines] == ["short", "x" * 71]
    assert " ".join(line.text for line in block.lines) == source

    verse = Verse(
        1,
        "1:1",
        ("q",),
        (VerseTranslation("131", source),),
    )
    with pytest.raises(LayoutOverflowError) as caught:
        build_layout(passage_with(verse), settings, fake_measurer)

    assert caught.value.element == "translation 131 for verse 1:1 line 2"
    assert caught.value.actual == (0, 710)
    assert caught.value.allowed == (0, 60)


def test_marker_width_is_reserved_only_when_marker_is_visible(
    fake_measurer, settings_factory
):
    common = {
        "quran_max_width": 100,
        "verse_number_resolution": Dimensions(20, 20),
        "verse_number_x_offset": 0,
    }
    visible = settings_factory(show_verse_numbers=True, **common)
    hidden = settings_factory(show_verse_numbers=False, **common)

    visible_block = layout_quran_text(("aaaa", "bbbb"), visible, fake_measurer)
    hidden_block = layout_quran_text(("aaaa", "bbbb"), hidden, fake_measurer)

    assert [line.text for line in visible_block.lines] == ["aaaa", "bbbb"]
    assert [line.text for line in hidden_block.lines] == ["aaaa bbbb"]


def test_empty_text_blocks_have_zero_height(fake_measurer, settings_factory):
    translations = (resolved_translation("131"),)
    settings = settings_factory(translations=translations)

    quran = layout_quran_text((), settings, fake_measurer)
    translation = layout_translation_text(
        VerseTranslation("131", ""), settings, fake_measurer
    )

    assert quran.lines == ()
    assert quran.height == 0
    assert translation.lines == ()
    assert translation.height == 0


def test_build_layout_preserves_centering_and_baseline(settings_factory):
    passage = passage_with(Verse(1, "1:1", ("بِسْمِ",), ()))

    image_layout = build_layout(passage, settings_factory(), FixedMeasurer(30, 10))

    assert image_layout.content_height == 10
    assert [(int(line.x), int(line.y), line.text) for line in image_layout.lines] == [
        (135, 105, "بِسْمِ")
    ]


def test_descender_is_included_below_the_shared_draw_baseline(settings_factory):
    passage = passage_with(Verse(1, "1:1", ("gypq",), ()))
    settings = settings_factory(resolution=Dimensions(100, 100))

    image_layout = build_layout(passage, settings, FixedMeasurer(30, 8, 4))

    assert image_layout.content_bounds is not None
    line = image_layout.lines[0]
    assert line.top == 44
    assert line.y == 52
    assert line.bottom == 56
    assert image_layout.content_bounds.top == 44
    assert image_layout.content_bounds.bottom == 56
    assert image_layout.content_height == 12


def test_descender_contributes_to_vertical_overflow(settings_factory):
    passage = passage_with(Verse(1, "1:1", ("gypq",), ()))
    settings = settings_factory(
        resolution=Dimensions(100, 100),
        total_y_offset=45,
    )

    with pytest.raises(LayoutOverflowError) as caught:
        build_layout(passage, settings, FixedMeasurer(30, 8, 4))

    assert caught.value.axis == "vertical"
    assert caught.value.actual == (89, 101)
    assert caught.value.allowed == (0, 100)
    assert caught.value.overflow == 1


def test_final_line_ink_measurement_controls_reported_bounds(settings_factory):
    class InkMeasurer:
        def __init__(self):
            self.ink_calls = []

        def measure(self, text, style):
            return TextMetrics(30, 8, 6, 2)

        def measure_ink(self, text, style):
            self.ink_calls.append(text)
            return TextMetrics(
                30,
                8,
                6,
                2,
                top_extent=10,
                bottom_extent=7,
            )

    passage = passage_with(Verse(1, "1:1", ("marked",), ()))
    settings = settings_factory(resolution=Dimensions(100, 100))
    measurer = InkMeasurer()

    image_layout = build_layout(passage, settings, measurer)

    assert set(measurer.ink_calls) == {"marked"}
    assert image_layout.content_bounds is not None
    line = image_layout.lines[0]
    assert line.top == line.y - 10
    assert line.bottom == line.y + 7
    assert image_layout.content_bounds.height == 17


def test_multilanguage_spacing_matches_positioned_bounds(settings_factory):
    translations = (
        resolved_translation("131"),
        resolved_translation("31", "fr"),
    )
    settings = settings_factory(translations=translations)
    verse = Verse(
        1,
        "1:1",
        ("q",),
        (VerseTranslation("131", "a"), VerseTranslation("31", "b")),
    )

    image_layout = build_layout(passage_with(verse), settings, FixedMeasurer(10, 12))

    assert image_layout.content_bounds is not None
    top = image_layout.content_bounds.top
    relative_tops = [line.top - top for line in image_layout.lines]
    assert relative_tops == [0, 42, 61]
    assert image_layout.content_height == 73
    assert image_layout.content_bounds.height == 73


def test_multiple_verses_use_only_interverse_spacing(settings_factory):
    passage = passage_with(
        Verse(1, "1:1", ("first",), ()),
        Verse(2, "1:2", ("second",), ()),
    )

    image_layout = build_layout(
        passage, settings_factory(space_between_verses=20), FixedMeasurer(10, 12)
    )

    assert image_layout.content_bounds is not None
    top = image_layout.content_bounds.top
    relative_tops = [line.top - top for line in image_layout.lines]
    assert relative_tops == [0, 32]
    assert image_layout.content_height == 44


def test_center_right_and_left_positions_are_explicit(settings_factory):
    measurer = FixedMeasurer(100, 10)
    quran_only = passage_with(Verse(1, "1:1", ("q",), ()))

    centered = build_layout(quran_only, settings_factory(), measurer)
    right_aligned = build_layout(
        quran_only,
        settings_factory(quran_x_position=30),
        measurer,
    )

    translations = (resolved_translation("131"),)
    translated = passage_with(
        Verse(1, "1:1", ("q",), (VerseTranslation("131", "translated"),))
    )
    left_aligned = build_layout(
        translated,
        settings_factory(
            translations=translations,
            translation_x_position=40,
        ),
        measurer,
    )

    assert centered.lines[0].x == 100
    assert right_aligned.lines[0].x == 170
    assert left_aligned.lines[1].x == 40


def test_visual_bearings_drive_alignment_and_marker_placement(settings_factory):
    measurer = FixedMeasurer(
        100,
        10,
        left_offset=-4,
        right_offset=106,
    )
    quran_only = passage_with(Verse(1, "1:1", ("q",), ()))

    centered = build_layout(quran_only, settings_factory(), measurer)
    right_aligned = build_layout(
        quran_only,
        settings_factory(quran_x_position=30),
        measurer,
    )
    marked = build_layout(
        quran_only,
        settings_factory(
            show_verse_numbers=True,
            verse_number_resolution=Dimensions(20, 20),
            verse_number_x_offset=5,
        ),
        measurer,
    )

    translations = (resolved_translation("131"),)
    translated = passage_with(
        Verse(1, "1:1", ("q",), (VerseTranslation("131", "translated"),))
    )
    left_aligned = build_layout(
        translated,
        settings_factory(
            translations=translations,
            translation_x_position=40,
        ),
        measurer,
    )

    assert (centered.lines[0].left, centered.lines[0].right) == (95, 205)
    assert (right_aligned.lines[0].left, right_aligned.lines[0].right) == (
        160,
        270,
    )
    assert left_aligned.lines[1].left == 40
    assert marked.markers[0].x + marked.markers[0].width == (marked.lines[0].left - 5)


def test_marker_reserve_validates_final_visual_width(settings_factory):
    settings = settings_factory(
        quran_max_width=129,
        show_verse_numbers=True,
        verse_number_resolution=Dimensions(20, 20),
        verse_number_x_offset=0,
    )
    passage = passage_with(Verse(1, "1:1", ("q",), ()))
    measurer = FixedMeasurer(
        100,
        10,
        left_offset=-4,
        right_offset=106,
    )

    with pytest.raises(LayoutOverflowError) as caught:
        build_layout(passage, settings, measurer)

    assert caught.value.element == "Quran text for verse 1:1 line 1"
    assert caught.value.actual == (0, 110)
    assert caught.value.allowed == (0, 109)
    assert caught.value.overflow == 1


def test_visual_width_reflow_handles_both_metric_directions_and_marker_reserve(
    settings_factory,
):
    class ThresholdMeasurer:
        def __init__(self):
            self.advance_widths = {
                "a": 30,
                "b": 30,
                "c": 30,
                "a b": 60,
                "a b c": 90,
                "x": 30,
                "y": 30,
                "x y": 61,
            }
            self.visual_widths = {
                **self.advance_widths,
                "a b c": 93,
                "x y": 60,
            }

        def measure(self, text, style):
            return TextMetrics(self.advance_widths[text], 10, 10, 0)

        def measure_ink(self, text, style):
            return TextMetrics(
                self.advance_widths[text],
                10,
                10,
                0,
                right_offset=self.visual_widths[text],
            )

    measurer = ThresholdMeasurer()
    overhanging = layout_quran_text(
        ("a", "b", "c"),
        settings_factory(quran_max_width=92),
        measurer,
    )
    narrower_ink = layout_quran_text(
        ("x", "y"),
        settings_factory(quran_max_width=60),
        measurer,
    )
    marked = layout_quran_text(
        ("a", "b", "c"),
        settings_factory(
            quran_max_width=112,
            show_verse_numbers=True,
            verse_number_resolution=Dimensions(20, 20),
            verse_number_x_offset=0,
        ),
        measurer,
    )

    assert [line.text for line in overhanging.lines] == ["a b", "c"]
    assert [line.text for line in narrower_ink.lines] == ["x y"]
    assert [line.text for line in marked.lines] == ["a b", "c"]
    assert marked.lines[-1].visual_width <= 92


def test_right_aligned_overflow_is_reported_instead_of_mirrored(
    settings_factory,
):
    settings = settings_factory(
        resolution=Dimensions(100, 100),
        quran_max_width=100,
        quran_x_position=10,
    )
    passage = passage_with(Verse(1, "1:1", ("q",), ()))

    with pytest.raises(LayoutOverflowError) as caught:
        build_layout(passage, settings, FixedMeasurer(95, 10))

    assert caught.value.axis == "horizontal"
    assert caught.value.actual == (-5, 90)
    assert caught.value.allowed == (0, 100)
    assert caught.value.overflow == 5


def test_visible_marker_participates_in_visual_bounds(settings_factory):
    passage = passage_with(Verse(1, "1:1", ("q",), ()))
    measurer = FixedMeasurer(30, 10)
    common = {
        "verse_number_resolution": Dimensions(55, 55),
        "verse_number_y_offset": -20,
    }

    visible = build_layout(
        passage,
        settings_factory(show_verse_numbers=True, **common),
        measurer,
    )
    hidden = build_layout(
        passage,
        settings_factory(show_verse_numbers=False, **common),
        measurer,
    )

    assert visible.content_bounds is not None
    assert visible.content_bounds.height == 55
    assert visible.content_height == 55
    assert len(visible.markers) == 1
    assert visible.markers[0].y == visible.content_bounds.top
    assert hidden.content_height == 10
    assert hidden.markers == ()


def test_reported_bounds_match_every_positioned_element(settings_factory):
    translations = (resolved_translation("131"),)
    passage = passage_with(
        Verse(1, "1:1", ("q",), (VerseTranslation("131", "translated"),))
    )
    settings = settings_factory(
        translations=translations,
        show_verse_numbers=True,
        verse_number_resolution=Dimensions(20, 20),
        verse_number_y_offset=-5,
    )

    image_layout = build_layout(passage, settings, FixedMeasurer(30, 10))

    assert image_layout.content_bounds is not None
    lefts = [line.left for line in image_layout.lines] + [
        marker.x for marker in image_layout.markers
    ]
    tops = [line.top for line in image_layout.lines] + [
        marker.y for marker in image_layout.markers
    ]
    rights = [line.right for line in image_layout.lines] + [
        marker.x + marker.width for marker in image_layout.markers
    ]
    bottoms = [line.bottom for line in image_layout.lines] + [
        marker.y + marker.height for marker in image_layout.markers
    ]
    assert image_layout.content_bounds.left == min(lefts)
    assert image_layout.content_bounds.top == min(tops)
    assert image_layout.content_bounds.right == max(rights)
    assert image_layout.content_bounds.bottom == max(bottoms)


def test_vertical_canvas_overflow_reports_bounds(settings_factory):
    passage = passage_with(Verse(1, "1:1", ("q",), ()))
    settings = settings_factory(resolution=Dimensions(300, 200))

    with pytest.raises(LayoutOverflowError) as caught:
        build_layout(passage, settings, FixedMeasurer(30, 210))

    assert caught.value.element == "content"
    assert caught.value.axis == "vertical"
    assert caught.value.actual == (-5, 205)
    assert caught.value.allowed == (0, 200)
    assert caught.value.overflow == 5
