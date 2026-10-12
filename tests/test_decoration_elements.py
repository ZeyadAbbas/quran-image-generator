import copy
from pathlib import Path

import pytest
from image_helpers import rgba_pixels
from PIL import Image
from test_api import fixture_request

from quran_image_generator.api import execute_request
from quran_image_generator.decoration_elements import prepare_element_fonts
from quran_image_generator.font_controls import FontWorkspace
from quran_image_generator.references import SourceSpan
from quran_image_generator.resources import asset_path
from quran_image_generator.scenes import (
    Layer,
    Scene,
    checked_asset,
    plan_scene,
    render_layer,
)


def request(tmp_path, spans=None):
    data = fixture_request(tmp_path)
    data["cues"] = [{"cue_id": "elements", "spans": spans or [__import__("dataclasses").asdict(SourceSpan(31, 9, 1, 8))]}]
    data.update(quotations=True, verse_numbers=True)
    data["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "provenance": {},
                       "styles": {"arabic": {"decoration_layout": "elements", "region": [0.05, 0.1, 0.95, 0.9], "max_lines": 8,
                                             "quotation_style": {"color": "#00CCFF"}, "marker_style": {"color": "#FFD700"}}}}
    return data


def image_path(result):
    return Path(result["job_directory"]) / result["assets"][0]["path"]


def test_actual_white_body_gold_numbers_and_blue_quotes_are_independent(tmp_path):
    data = request(tmp_path)
    before = execute_request(data).to_dict()
    assert before["status"] == "complete", before
    with Image.open(image_path(before)) as image:
        colors = set(rgba_pixels(image))
        assert {(255, 255, 255, 255), (255, 215, 0, 255), (0, 204, 255, 255)} <= colors
    data["profile"]["styles"]["arabic"]["marker_style"]["color"] = "#FF0000"
    after = execute_request(data).to_dict()
    with Image.open(image_path(before)) as a, Image.open(image_path(after)) as b:
        a, b = a.convert("RGBA"), b.convert("RGBA")
        white_a = bytes(
            pixel[3] if pixel[:3] == (255, 255, 255) else 0 for pixel in rgba_pixels(a)
        )
        white_b = bytes(
            pixel[3] if pixel[:3] == (255, 255, 255) else 0 for pixel in rgba_pixels(b)
        )
        assert white_a == white_b
    assert before["cues"][0]["arabic"] == after["cues"][0]["arabic"]
    assert before["cues"][0]["source_spans"] == after["cues"][0]["source_spans"]


def test_every_repeated_ending_has_its_own_source_association_and_same_style(tmp_path):
    span = __import__("dataclasses").asdict(SourceSpan(31, 9, 6, 8))
    singles = execute_request(request(tmp_path, [span])).to_dict()
    repeats = execute_request(request(tmp_path, [span, span])).to_dict()
    markers = [v for v in repeats["cues"][0]["layers"][0]["elements"] if v["kind"] == "marker"]
    single = next(v for v in singles["cues"][0]["layers"][0]["elements"] if v["kind"] == "marker")
    assert len(markers) == 2 and {v["id"] for v in markers} == {"marker:0", "marker:1"}
    assert [v["occurrence"] for v in markers] == [0, 1]
    assert all(v["ayah"] == 9 and v["source_word"] == 8 for v in markers)
    assert all(v["font_size"] == single["font_size"] and v["style"] == single["style"] for v in markers)


def test_partial_phrases_and_separate_basmala_never_receive_an_ending(tmp_path):
    spans = [__import__("dataclasses").asdict(SourceSpan(0, 0, 1, 4)), __import__("dataclasses").asdict(SourceSpan(31, 9, 1, 5))]
    result = execute_request(request(tmp_path, spans)).to_dict()
    assert result["status"] == "complete"
    assert not any(v["kind"] == "marker" for v in result["cues"][0]["layers"][0]["elements"])


def test_toggle_open_quote_marker_and_outline_separately(tmp_path):
    data = request(tmp_path)
    data["profile"]["styles"]["arabic"].update(quote_open_enabled=False, outline_width=0)
    result = execute_request(data).to_dict()
    kinds = [v["kind"] for v in result["cues"][0]["layers"][0]["elements"]]
    assert "quote_open" not in kinds and "quote_close" in kinds and "marker" in kinds
    data["profile"]["styles"]["arabic"]["marker_style"]["enabled"] = False
    result = execute_request(data).to_dict()
    kinds = [v["kind"] for v in result["cues"][0]["layers"][0]["elements"]]
    assert "marker" not in kinds and "quote_close" in kinds


def test_separate_fonts_and_true_marker_cannot_be_stranded_when_wrapping(tmp_path):
    data = request(tmp_path)
    latin = str(asset_path("fonts", "multilingual_fonts", "am.ttf"))
    selector = {"path": latin, "sha256": checked_asset(latin), "license": "fixture", "attribution": "Bundled Noto"}
    data["assets"] = {"markers": selector, "quotes": selector}
    data["profile"]["styles"]["arabic"].update(numeral_system="latin", quote_open="(", quote_close=")", marker_prefix="[", marker_suffix="]", region=[0.33, 0.1, 0.67, 0.9], fit="shrink")
    result = execute_request(data).to_dict()
    assert result["status"] == "complete", result
    elements = result["cues"][0]["layers"][0]["elements"]
    marker = next(v for v in elements if v["kind"] == "marker")
    assert marker["font_sha256"] == selector["sha256"]
    assert result["cues"][0]["layers"][0]["font_info"]["effective"]["font_size_output_pixels"] == result["cues"][0]["layers"][0]["font_size"]
    assert any(v["kind"] == "body" and v["line_index"] == marker["line_index"] for v in elements)
    assert marker["text"] == "[9]"
    data["assets"]["markers"]["sha256"] = "0" * 64
    assert execute_request(data).payload["cues"][0]["error"]["code"] == "changed_asset"


def test_crop_recomposition_bounds_and_whole_block_center(tmp_path):
    data = request(tmp_path)
    data["profile"]["styles"]["arabic"]["marker_style"].update(outline_width=1, shadow_offset=[2, 3], shadow_blur=1, shadow_opacity=0.5)
    full = execute_request(data).to_dict()
    data["cropped"] = True
    crop = execute_request(data).to_dict()
    with Image.open(image_path(full)) as a, Image.open(image_path(crop)) as b, Image.new("RGBA", a.size) as recomposed:
        recomposed.alpha_composite(b, tuple(crop["assets"][0]["offset"]))
        assert recomposed.tobytes() == a.tobytes()
        actual = a.getbbox()
    plan = full["cues"][0]["layers"][0]
    assert all(a >= p - 1 for a, p in zip(actual[:2], plan["bounds"][:2], strict=True))
    assert all(a <= p + 1 for a, p in zip(actual[2:], plan["bounds"][2:], strict=True))
    assert (plan["bounds"][0] + plan["bounds"][2]) / 2 == pytest.approx(288, abs=1)


def test_marker_after_quote_and_source_breaks(tmp_path):
    data = request(tmp_path)
    data["profile"]["styles"]["arabic"].update(marker_placement="after_quote", line_height=2)
    data["cues"][0]["line_breaks"] = [{"span_occurrence": 0, "source_word": 4, "mode": "forced"}]
    result = execute_request(data).to_dict()
    assert result["status"] == "complete", result
    plan = result["cues"][0]["layers"][0]
    assert len(plan["lines"]) == 2
    final = [v["kind"] for v in plan["elements"] if v["line_index"] == 1]
    assert final[-2:] == ["quote_close", "marker"]


def test_marker_looking_body_text_is_never_reclassified(tmp_path):
    font = str(asset_path("fonts", "quran_font.ttf"))
    layer = Layer("arabic", "٩ خَلَقَ", font, decoration_layout="elements", marker_style={"color": "#FFD700"})
    with FontWorkspace() as fonts:
        layer = fonts.prepare(layer)
        layer = prepare_element_fonts(layer, {}, tmp_path, fonts)
        scene = Scene(576, 1024, (layer,))
        plan = plan_scene(scene)[0]
        assert all(v["kind"] == "body" for v in plan.elements)
        render_layer(scene, plan, tmp_path / "ordinary-digit.png")


def test_old_requests_retain_legacy_pixels(tmp_path):
    data = request(tmp_path)
    data.pop("profile")
    legacy = execute_request(data).to_dict()
    explicit = copy.deepcopy(data)
    explicit["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "provenance": {}, "styles": {"arabic": {"decoration_layout": "legacy"}}}
    replay = execute_request(explicit).to_dict()
    assert replay["assets"][0]["sha256"] == legacy["assets"][0]["sha256"]


def test_decoration_edit_does_not_change_translation_review_or_binding(tmp_path):
    from test_bindings import fixture_dataset

    data = request(tmp_path, [__import__("dataclasses").asdict(SourceSpan(31, 9, 1, 5))])
    data["translation_dataset"] = fixture_dataset().to_dict()
    data["cues"][0].update(translation_policy="required", translation_binding_id="31-9-prefix")
    before = execute_request(data).to_dict()
    data["profile"]["styles"]["arabic"]["quotation_style"]["opacity"] = 0.5
    after = execute_request(data).to_dict()
    assert before["status"] == after["status"] == "complete"
    assert before["cues"][0]["translation"] == after["cues"][0]["translation"]
    translation_before = next(v for v in before["assets"] if "translation" in v["roles"])
    translation_after = next(v for v in after["assets"] if "translation" in v["roles"])
    assert translation_before["sha256"] == translation_after["sha256"]
