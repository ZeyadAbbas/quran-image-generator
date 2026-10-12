from dataclasses import asdict, replace
from pathlib import Path

import pytest
from PIL import Image
from test_api import fixture_request

from quran_image_generator.api import execute_request, runtime_identity
from quran_image_generator.caption_editor import CaptionDocument, parse_style_value
from quran_image_generator.excerpts import ExcerptRequest, select_excerpt
from quran_image_generator.references import ReferenceError, SourceSpan
from quran_image_generator.resources import asset_path
from quran_image_generator.scenes import Layer, Scene, plan_scene, render_layer
from quran_image_generator.shaping import ShapedFont
from quran_image_generator.typography import apply_break_hints


@pytest.mark.skipif(not runtime_identity()["native_raqm"], reason="Nonzero spacing advertises native RAQM requirement")
def test_native_arabic_spacing_retains_glyph_masks():
    path = str(asset_path("fonts", "quran_font.ttf"))
    text = select_excerpt(ExcerptRequest("a", (SourceSpan(1, 1, 1, 2),))).text
    original = ShapedFont(path, 30, "rtl")
    spaced = ShapedFont(path, 30, "rtl", word_spacing=12)
    # Both complete-line native renders have the same marks/glyph coverage;
    # only the native space advance grows by the requested amount.
    if original.pillow:
        original.pillow = None
        from quran_image_generator.rendering import WandTextMeasurer
        original._measurer = WandTextMeasurer()
    assert spaced.advance(text) - original.advance(text) == pytest.approx(12, abs=1)
    with Image.new("RGBA", (400, 160)) as a, Image.new("RGBA", (400, 160)) as b:
        original.paint(a, text, 40, 90, "white")
        spaced.paint(b, text, 40, 90, "white")
        assert a.getbbox()[3] - a.getbbox()[1] == b.getbbox()[3] - b.getbbox()[1]
        assert sum(a.getchannel("A").tobytes()) == pytest.approx(sum(b.getchannel("A").tobytes()), rel=0.005)


@pytest.mark.parametrize("width,height", [(576, 1024), (1080, 1920)])
def test_spacing_wrap_shrink_and_pixels_fit_envelope(tmp_path, width, height):
    font = str(asset_path("fonts", "quran_font.ttf"))
    excerpt = select_excerpt(ExcerptRequest("a", (SourceSpan(1, 1, 1, 4),)))
    scene = Scene(width, height, (Layer("arabic", excerpt.text, font, word_spacing=0.4, fit="shrink", region=(0.35, 0.35, 0.65, 0.65)),))
    plan = plan_scene(scene)[0]
    asset = render_layer(scene, plan, tmp_path / "spaced.png", cropped=True)
    assert asset.bounds and plan.bounds
    assert all(a >= p - 1 for a, p in zip(asset.bounds[:2], plan.bounds[:2], strict=True))
    assert all(a <= p + 1 for a, p in zip(asset.bounds[2:], plan.bounds[2:], strict=True))
    assert plan.typography["word_spacing_pixels"] == plan.font_size * 0.4
    assert " ".join(v[0] for v in plan.lines) == excerpt.text


def test_fixed_baseline_step_independent_of_line_ink():
    font = str(asset_path("fonts", "multilingual_fonts", "am.ttf"))
    steps = []
    for text in ("ACE\nACE", "gyp\ngyp", "cafe\u0301\ncafe\u0301"):
        scene = Scene(576, 1024, (Layer("translation", text, font, direction="ltr", line_height=1.5),))
        plan = plan_scene(scene)[0]
        steps.append(plan.lines[1][2] - plan.lines[0][2])
    assert steps == [45, 45, 45]
    with pytest.raises(ReferenceError) as error:
        plan_scene(Scene(576, 1024, (Layer("translation", "gyp\ngyp", font, direction="ltr", line_height=0.1),)))
    assert error.value.code == "line_height_collision"


def test_latin_tracking_keeps_combining_cluster_and_rejects_connected_scripts(tmp_path):
    font = str(asset_path("fonts", "multilingual_fonts", "am.ttf"))
    layer = Layer("translation", "cafe\u0301 office", font, direction="ltr", tracking=0.1)
    plan = plan_scene(Scene(576, 1024, (layer,)))[0]
    assert plan.lines[0][0] == layer.text
    shaped = ShapedFont(font, 30, "ltr", tracking=3)
    assert [run[0] for run in shaped._tracked_runs("e\u0301a")] == ["e\u0301", "a"]
    render_layer(Scene(576, 1024, (layer,)), plan, tmp_path / "latin.png")
    for text, direction in (("بسم", "rtl"), ("ब", "ltr"), ("\u0301e", "ltr")):
        with pytest.raises(ReferenceError) as error:
            ShapedFont(font, 30, direction, tracking=3).getbbox(text)
        assert error.value.code == "unsupported_tracking"


def test_repeated_occurrence_breaks_preserve_source_and_bindings(tmp_path):
    data = fixture_request(tmp_path, "layout")
    span = asdict(SourceSpan(31, 9, 1, 5))
    data["cues"] = [{"cue_id": "repeat", "spans": [span, span],
                     "line_breaks": [{"span_occurrence": 1, "source_word": 2, "mode": "forced"}]}]
    data["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "provenance": {},
                       "styles": {"arabic": {"max_lines": 8, "region": [0.05, 0.1, 0.95, 0.9]}}}
    result = execute_request(data).to_dict()
    assert result["status"] == "complete"
    entry = result["cues"][0]
    source = select_excerpt(ExcerptRequest("repeat", (SourceSpan(31, 9, 1, 5),) * 2)).text
    assert entry["arabic"] == source
    assert " ".join(line[0] for line in entry["layers"][0]["lines"]) == source
    assert len(entry["layers"][0]["lines"]) == 2
    assert entry["layers"][0]["typography"]["forced_breaks"]


def test_preferred_break_is_only_used_when_line_needs_wrapping():
    font = str(asset_path("fonts", "multilingual_fonts", "am.ttf"))
    layer = Layer("translation", "one two three four five", font, direction="ltr", preferred_breaks=(7,))
    wide = plan_scene(Scene(576, 1024, (layer,)))[0]
    narrow = plan_scene(Scene(576, 1024, (replace(layer, region=(0.35, 0.1, 0.65, 0.9), max_lines=8),)))[0]
    assert len(wide.lines) == 1
    assert narrow.lines[0][0] == "one two"


def test_indivisible_break_rejected_and_gui_json_roundtrip(tmp_path):
    excerpt = select_excerpt(ExcerptRequest("joined", (SourceSpan(5, 72, 13, 15),)))
    font = str(asset_path("fonts", "quran_font.ttf"))
    scene = Scene(576, 1024, (Layer("arabic", excerpt.text, font),))
    with pytest.raises(ReferenceError) as error:
        apply_break_hints(excerpt, scene, [{"span_occurrence": 0, "source_word": 13, "mode": "forced"}], quotations=False, verse_numbers=False)
    assert error.value.code == "invalid_break" and error.value.details["cause"] == "mapping_boundary"
    document = CaptionDocument(root=tmp_path)
    document.set_style("arabic", {"word_spacing": parse_style_value("word_spacing", "0.15"), "line_height": 1.6})
    document.data["cues"][0]["line_breaks"] = [{"span_occurrence": 0, "source_word": 2, "mode": "forced"}]
    path = tmp_path / "typography.json"
    document.save(path)
    assert CaptionDocument.load(path).request().to_dict() == document.request().to_dict()


def test_zero_typography_is_pixel_identical_and_identity_changes(tmp_path):
    data = fixture_request(tmp_path)
    old = execute_request(data).to_dict()
    data["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "provenance": {},
                       "styles": {"arabic": {"word_spacing": 0, "line_height": 0, "tracking": 0}}}
    zero = execute_request(data).to_dict()
    assert old["assets"][0]["sha256"] == zero["assets"][0]["sha256"]
    data["profile"]["styles"]["arabic"]["word_spacing"] = 0.2
    changed = execute_request(data).to_dict()
    assert changed["status"] == "complete", changed
    assert changed["assets"][0]["asset_id"] != zero["assets"][0]["asset_id"]
    assert Path(changed["job_directory"]).is_dir()


def test_word_spacing_backend_limitation_is_explicit(monkeypatch):
    import wand.version

    from quran_image_generator import shaping

    monkeypatch.setattr(shaping.features, "check_feature", lambda name: True)
    monkeypatch.setattr(wand.version, "MAGICK_VERSION_DELEGATES", "freetype")
    with pytest.raises(ReferenceError) as error:
        ShapedFont(str(asset_path("fonts", "quran_font.ttf")), 30, "rtl", word_spacing=3)
    assert error.value.code == "unsupported_shaping_option"
    assert error.value.details["field"] == "word_spacing"
