from dataclasses import replace
from math import ceil, floor
from pathlib import Path

import pytest
from wand.image import Image as WandImage

import rendering
from layout import (
    ImageLayout,
    LayoutOverflowError,
    PositionedLine,
    TextMetrics,
    TextStyle,
    VerseMarker,
    build_layout,
)
from models import Passage, Verse
from rendering import WandImageRenderer, WandTextMeasurer
from settings import Dimensions

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _trimmed_pixel_bounds(path):
    with (
        WandImage(filename=str(path)) as rendered,
        rendered.clone() as trimmed,
    ):
        trimmed.trim()
        return (
            trimmed.page_x,
            trimmed.page_y,
            trimmed.page_x + trimmed.width,
            trimmed.page_y + trimmed.height,
        )


def test_wand_renderer_draws_text_and_saves_destination(
    monkeypatch, settings_factory, tmp_path
):
    created_images = []
    drawn_text = []
    applied_images = []
    saved_paths = []
    composites = []
    resized = []

    class FakeImage:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created_images.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def save(self, filename):
            saved_paths.append(filename)

        def composite(self, other, x, y):
            composites.append((self, other, x, y))

        def resize(self, width, height):
            resized.append((self, width, height))

    class FakeDrawing:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def text(self, x, y, text):
            drawn_text.append((x, y, text))

        def __call__(self, image):
            applied_images.append(image)

    monkeypatch.setattr(rendering, "Image", FakeImage)
    monkeypatch.setattr(rendering, "Drawing", FakeDrawing)
    style = TextStyle("Fixture Quran", 24, "#FFFFFF", 0.0, 200, " ")
    image_layout = ImageLayout(
        width=300,
        height=200,
        content_height=10,
        lines=(
            PositionedLine(
                "verse",
                12.9,
                34.8,
                TextMetrics(50, 10, 10, 0),
                style,
            ),
        ),
        markers=(VerseMarker(1, 2.9, 3.9, 55, 55),),
    )
    destination = tmp_path / "output.png"
    settings = settings_factory(background_image=tmp_path / "background.png")

    result = WandImageRenderer().render(image_layout, settings, destination)

    assert result == destination
    assert created_images[0].kwargs == {
        "width": 300,
        "height": 200,
        "pseudo": "xc:#000000",
    }
    assert drawn_text == [(12, 34, "verse")]
    assert applied_images == [created_images[0]]
    assert saved_paths == [str(destination)]
    assert created_images[1].kwargs == {"filename": str(settings.background_image)}
    assert created_images[2].kwargs == {
        "filename": str(Path("assets/verse_numbers/1.png"))
    }
    assert composites == [
        (created_images[0], created_images[1], 0, 0),
        (created_images[0], created_images[2], 2, 3),
    ]
    assert resized == [(created_images[2], 55, 55)]


def test_wand_bounds_include_pixels_rendered_below_the_baseline(
    settings_factory, tmp_path
):
    font = PROJECT_ROOT / "assets" / "fonts" / "multilingual_fonts" / "am.ttf"
    settings = settings_factory(
        resolution=Dimensions(400, 300),
        quran_font=font,
        quran_font_size=80,
        quran_max_width=350,
        background_color="#000000",
        quran_color="#FFFFFF",
        show_verse_numbers=False,
    )
    passage = Passage(1, "Test", (Verse(1, "1:1", ("gypq",), ()),))
    image_layout = build_layout(passage, settings, WandTextMeasurer())
    destination = tmp_path / "descender-regression.png"

    WandImageRenderer().render(image_layout, settings, destination)

    assert image_layout.content_bounds is not None
    line = image_layout.lines[0]
    assert line.descender > 0
    assert line.bottom > line.y
    pixel_bounds = _trimmed_pixel_bounds(destination)

    assert pixel_bounds[3] > int(line.y)
    assert pixel_bounds[1] >= floor(image_layout.content_bounds.top) - 1
    assert pixel_bounds[3] <= ceil(image_layout.content_bounds.bottom) + 1


def test_quran_combining_marks_are_bounded_and_unsafe_shift_is_rejected(
    settings_factory, tmp_path
):
    font = PROJECT_ROOT / "assets" / "fonts" / "quran_font.ttf"
    settings = settings_factory(
        resolution=Dimensions(900, 300),
        quran_font=font,
        quran_font_size=80,
        quran_max_width=850,
        background_color="#000000",
        quran_color="#FFFFFF",
        show_verse_numbers=False,
    )
    text = "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ"
    passage = Passage(1, "Test", (Verse(1, "1:1", (text,), ()),))
    image_layout = build_layout(passage, settings, WandTextMeasurer())
    destination = tmp_path / "quran-combining-marks.png"

    WandImageRenderer().render(image_layout, settings, destination)

    assert image_layout.content_bounds is not None
    line = image_layout.lines[0]
    pixel_bounds = _trimmed_pixel_bounds(destination)
    assert pixel_bounds[1] < floor(line.y - line.ascender)
    assert pixel_bounds[3] > ceil(line.y + line.descender)
    assert pixel_bounds[1] >= floor(image_layout.content_bounds.top) - 1
    assert pixel_bounds[3] <= ceil(image_layout.content_bounds.bottom) + 1
    assert abs(pixel_bounds[1] - image_layout.content_bounds.top) <= 1
    assert abs(pixel_bounds[3] - image_layout.content_bounds.bottom) <= 1

    # This moves the old ascender-only top just inside the canvas, even though
    # the real Arabic ink would cross the edge. The complete envelope must
    # reject it before rendering.
    unsafe_offset = -floor(line.y - line.ascender)
    assert pixel_bounds[1] + unsafe_offset < 0
    unsafe_settings = replace(settings, total_y_offset=unsafe_offset)

    with pytest.raises(LayoutOverflowError) as caught:
        build_layout(passage, unsafe_settings, WandTextMeasurer())

    assert caught.value.axis == "vertical"
    assert caught.value.actual[0] < 0


def test_quran_visual_right_edge_aligns_without_silent_clipping(
    settings_factory, tmp_path
):
    font = PROJECT_ROOT / "assets" / "fonts" / "quran_font.ttf"
    edge_settings = settings_factory(
        resolution=Dimensions(900, 300),
        quran_font=font,
        quran_font_size=80,
        quran_x_position=0,
        quran_max_width=850,
        background_color="#000000",
        quran_color="#FFFFFF",
        show_verse_numbers=False,
    )
    room_settings = replace(
        edge_settings,
        resolution=Dimensions(920, 300),
        quran_x_position=20,
    )
    text = "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ"
    passage = Passage(1, "Test", (Verse(1, "1:1", (text,), ()),))
    edge_layout = build_layout(passage, edge_settings, WandTextMeasurer())
    room_layout = build_layout(passage, room_settings, WandTextMeasurer())
    edge_destination = tmp_path / "quran-at-right-edge.png"
    room_destination = tmp_path / "quran-with-right-room.png"

    WandImageRenderer().render(edge_layout, edge_settings, edge_destination)
    WandImageRenderer().render(room_layout, room_settings, room_destination)

    assert edge_layout.content_bounds is not None
    edge_line = edge_layout.lines[0]
    room_line = room_layout.lines[0]
    edge_pixels = _trimmed_pixel_bounds(edge_destination)
    room_pixels = _trimmed_pixel_bounds(room_destination)
    assert edge_line.right == 900
    assert room_line.right == 900
    assert edge_pixels[0] == room_pixels[0]
    assert edge_pixels[2] == room_pixels[2]
    assert edge_pixels[2] > ceil(edge_line.x + edge_line.width)
    assert abs(edge_pixels[0] - edge_line.left) <= 1
    assert abs(edge_pixels[2] - edge_line.right) <= 1
    assert edge_pixels[0] >= floor(edge_layout.content_bounds.left) - 1
    assert edge_pixels[2] <= ceil(edge_layout.content_bounds.right) + 1


def test_quran_wrapping_uses_final_visual_width_near_the_limit(
    settings_factory,
):
    font = PROJECT_ROOT / "assets" / "fonts" / "quran_font.ttf"
    common = {
        "resolution": Dimensions(900, 400),
        "quran_font": font,
        "quran_font_size": 80,
        "show_verse_numbers": False,
    }
    words = ("بِسْمِ", "اللَّهِ", "الرَّحْمَٰنِ", "الرَّحِيمِ")
    passage = Passage(1, "Test", (Verse(1, "1:1", words, ()),))
    generous_settings = settings_factory(quran_max_width=2_000, **common)
    measurer = WandTextMeasurer()
    probe = build_layout(passage, generous_settings, measurer)
    probe_line = probe.lines[0]
    threshold = ceil(probe_line.width)

    assert threshold < probe_line.visual_width

    overhanging = build_layout(
        passage,
        replace(generous_settings, quran_max_width=threshold),
        measurer,
    )

    assert len(overhanging.lines) > 1
    assert all(
        line.visual_width <= threshold for line in overhanging.lines
    )

    marked = build_layout(
        passage,
        replace(
            generous_settings,
            quran_max_width=threshold + 60,
            show_verse_numbers=True,
            verse_number_resolution=Dimensions(55, 55),
            verse_number_x_offset=5,
        ),
        measurer,
    )

    assert len(marked.lines) > 1
    assert marked.lines[-1].visual_width <= threshold
    assert marked.markers[0].x + marked.markers[0].width == (
        marked.lines[-1].left - 5
    )
