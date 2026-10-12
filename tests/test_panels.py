import copy
from pathlib import Path

import pytest
from image_helpers import rgba_pixels
from PIL import Image
from test_api import fixture_request
from test_bindings import fixture_dataset

from quran_image_generator.api import execute_request


def panel_request(tmp_path):
    data = fixture_request(tmp_path)
    data["cues"] = data["cues"][:1]
    data["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "provenance": {},
                       "styles": {"arabic": {"panel": {"color": "#000000", "opacity": 0.6, "padding": [0.5, 0.35], "corner_radius": 0.25}}}}
    return data


def path(result, role="arabic"):
    record = next(a for a in result["assets"] if role in a["roles"])
    return Path(result["job_directory"]) / record["path"]


def test_panel_and_text_have_independent_alpha_and_transparent_exterior(tmp_path):
    result = execute_request(panel_request(tmp_path)).to_dict()
    assert result["status"] == "complete", result
    with Image.open(path(result)) as im:
        colors = set(rgba_pixels(im))
        assert (0, 0, 0, 153) in colors and (255, 255, 255, 255) in colors
        assert im.getpixel((0, 0))[3] == 0
    data = panel_request(tmp_path)
    data["profile"]["styles"]["arabic"]["opacity"] = 0.5
    result = execute_request(data).to_dict()
    with Image.open(path(result)) as im:
        assert (0, 0, 0, 153) in set(rgba_pixels(im))


def test_multiline_line_panels_differ_from_block_and_shrink_resolves_em(tmp_path):
    data = panel_request(tmp_path)
    data["profile"]["styles"]["arabic"].update(region=[0.3, 0.1, 0.7, 0.9], fit="shrink", max_lines=8)
    data["profile"]["styles"]["arabic"]["panel"]["mode"] = "line"
    line = execute_request(data).to_dict()
    assert line["status"] == "complete", line
    plan = line["cues"][0]["layers"][0]
    assert len(plan["panels"]) == len(plan["lines"]) > 1
    assert plan["panels"][0]["padding_pixels"][0] == plan["font_size"] * 0.5
    data["profile"]["styles"]["arabic"]["panel"]["mode"] = "block"
    block = execute_request(data).to_dict()
    assert len(block["cues"][0]["layers"][0]["panels"]) == 1
    assert block["assets"][0]["sha256"] != line["assets"][0]["sha256"]


def test_panel_border_shadow_decorations_crop_and_bounds(tmp_path):
    data = panel_request(tmp_path)
    data.update(quotations=True, verse_numbers=True)
    style = data["profile"]["styles"]["arabic"]
    style.update(decoration_layout="elements", region=[0.05, 0.1, 0.95, 0.9])
    style["panel"].update(border_width=0.05, border_color="#FFD700", shadow_offset=[0.1, 0.1], shadow_blur=0.05, shadow_opacity=0.4)
    full = execute_request(data).to_dict()
    assert full["status"] == "complete", full
    data["cropped"] = True
    crop = execute_request(data).to_dict()
    with Image.open(path(full)) as a, Image.open(path(crop)) as b, Image.new("RGBA", a.size) as reconstructed:
        reconstructed.alpha_composite(b, tuple(crop["assets"][0]["offset"]))
        assert reconstructed.tobytes() == a.tobytes()
        actual = a.getbbox()
    bounds = full["cues"][0]["layers"][0]["bounds"]
    assert all(a >= p - 1 for a, p in zip(actual[:2], bounds[:2], strict=True))
    assert all(a <= p + 1 for a, p in zip(actual[2:], bounds[2:], strict=True))


def test_shared_group_backplate_and_hidden_translation_reclaim_bounds(tmp_path):
    data = fixture_request(tmp_path)
    data["cues"] = data["cues"][:1]
    data["translation_dataset"] = fixture_dataset().to_dict()
    data["cues"][0].update(translation_policy="required", translation_binding_id="31-9-prefix")
    data["caption_groups"] = [{"group_id": "caption", "layers": ["arabic", "translation"], "panel": {"opacity": 0.6}}]
    full = execute_request(data).to_dict()
    assert full["status"] == "complete", full
    group = next(v for v in full["cues"][0]["layers"] if v["layer"]["kind"] == "panel")
    assert group["asset_id"] in full["cues"][0]["asset_ids"]
    data["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "provenance": {}, "styles": {"translation": {"enabled": False}}}
    hidden = execute_request(data).to_dict()
    assert hidden["status"] == "complete", hidden
    smaller = next(v for v in hidden["cues"][0]["layers"] if v["layer"]["kind"] == "panel")
    assert smaller["bounds"][3] < group["bounds"][3]
    assert smaller["asset_id"] != group["asset_id"]
    data.pop("translation_dataset")
    data["cues"][0]["translation_policy"] = "review"
    omitted = execute_request(data).to_dict()
    assert omitted["status"] == "needs_review"
    assert any(v["layer"]["kind"] == "panel" for v in omitted["cues"][0]["layers"])


def test_panel_overflow_fails_before_output_and_disabled_panels_are_legacy(tmp_path):
    data = panel_request(tmp_path)
    data["profile"]["styles"]["arabic"]["panel"]["padding"] = [64, 64]
    result = execute_request(data).to_dict()
    assert result["status"] == "failed"
    assert result["cues"][0]["error"]["details"]["constraint"] == "panel_envelope"
    assert not (tmp_path / "output with spaces").exists()
    legacy = fixture_request(tmp_path)
    before = execute_request(legacy).to_dict()
    after_data = copy.deepcopy(legacy)
    after_data["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "provenance": {}, "styles": {"arabic": {"panel": {"enabled": False}}}}
    after = execute_request(after_data).to_dict()
    assert before["assets"][0]["sha256"] == after["assets"][0]["sha256"]


def test_region_mode_and_empty_layers_do_not_create_accidental_panels(tmp_path):
    data = panel_request(tmp_path)
    data["profile"]["styles"]["arabic"]["panel"].update(mode="region", region=[0.05, 0.35, 0.95, 0.53])
    assert execute_request(data).to_dict()["status"] == "complete"
    data["profile"]["styles"]["arabic"]["enabled"] = False
    result = execute_request(data).to_dict()
    assert result["assets"] == []
    assert result["cues"][0]["layers"][0]["panels"] == []


@pytest.mark.parametrize(
    "invalid", [{"gradient": []}, {"opacity": 2}, {"padding": [-1, 0]}]
)
def test_panel_fields_use_precise_shared_schema_diagnostics(tmp_path, invalid):
    data = panel_request(tmp_path)
    data["profile"]["styles"]["arabic"]["panel"] = invalid
    result = execute_request(data).to_dict()
    assert result["error"]["details"]["path"].startswith("/profile/styles/arabic/panel/")
