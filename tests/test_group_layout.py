import copy
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image
from test_api import fixture_request
from test_bindings import fixture_dataset

from quran_image_generator.api import execute_request
from quran_image_generator.resources import asset_path
from quran_image_generator.scenes import Layer, Scene, plan_scene, render_layer


@pytest.mark.parametrize("width,height", [(1080, 1920), (1920, 1080), (1080, 1080), (3840, 2160)])
def test_real_ink_bottom_stays_at_requested_edge_for_distinct_fonts(tmp_path, width, height):
    fonts = [str(asset_path("fonts", "multilingual_fonts", name)) for name in ("am.ttf", "hi.ttf")]
    bottoms = []
    for index, font in enumerate(fonts):
        text = "Caption descender gyp" if index == 0 else "किरण"
        layer = Layer("translation", text, font, direction="ltr", anchor=(0.5, 0.92), anchor_mode="ink_bottom", scale_basis="short_side",
                      region=(0.05, 0.1, 0.95, 0.96))
        scene = Scene(width, height, (layer,))
        plan = plan_scene(scene)[0]
        asset = render_layer(scene, plan, tmp_path / f"ink-{index}.png")
        bottoms.append(asset.bounds[3])
        assert plan.layout_info["anchor_mode"] == "ink_bottom"
    assert all(abs(value - round(height * 0.92)) <= 1 for value in bottoms)


def group_request(tmp_path):
    data = fixture_request(tmp_path)
    data["cues"] = data["cues"][:1]
    data["translation_dataset"] = fixture_dataset().to_dict()
    data["cues"][0].update(translation_policy="required", translation_binding_id="31-9-prefix")
    data["caption_groups"] = [{"group_id": "caption", "mode": "flow", "layers": ["arabic", "translation"],
                               "region": [0.05, 0.1, 0.95, 0.92], "vertical_alignment": "bottom", "gap": 0.6,
                               "collision": "reject", "fit": "shrink", "panel": {"opacity": 0.6}}]
    return data


def test_joint_flow_has_real_gap_panel_bounds_and_hidden_slots_reclaimed(tmp_path):
    data = group_request(tmp_path)
    result = execute_request(data).to_dict()
    assert result["status"] == "complete", result
    text = [p for p in result["cues"][0]["layers"] if p["layer"]["kind"] == "text"]
    assert text[1]["bounds"][1] - text[0]["bounds"][3] == pytest.approx(18, abs=1)
    panel = next(p for p in result["cues"][0]["layers"] if p["layer"]["kind"] == "panel")
    assert panel["bounds"][3] == round(0.92 * 1024)
    for p in text:
        assert p["layout_info"]["effect_bounds"] == p["bounds"]
    data["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "provenance": {}, "styles": {"translation": {"enabled": False}}}
    hidden = execute_request(data).to_dict()
    assert hidden["status"] == "complete"
    hidden_panel = next(p for p in hidden["cues"][0]["layers"] if p["layer"]["kind"] == "panel")
    assert hidden_panel["bounds"][1] > panel["bounds"][1]


def test_declared_collision_rejects_and_intentional_overlay_is_unchanged(tmp_path):
    data = group_request(tmp_path)
    data["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "provenance": {},
                       "styles": {"translation": {"anchor": [0.5, 0.5], "baseline_anchor": "last", "region": [0.05, 0.35, 0.95, 0.53]}}}
    data["caption_groups"] = [{"group_id": "overlap", "layers": ["arabic", "translation"], "collision": "reject"}]
    result = execute_request(data).to_dict()
    assert result["cues"][0]["error"]["code"] == "layer_collision"
    data["caption_groups"][0]["collision"] = "allow"
    assert execute_request(data).to_dict()["status"] == "complete"


def test_impossible_joint_fit_identifies_child_and_every_cue_without_png(tmp_path):
    data = group_request(tmp_path)
    data["operation"] = "layout"
    data["caption_groups"][0]["region"] = [0.49, 0.49, 0.51, 0.51]
    data["caption_groups"][0]["panel"] = {"enabled": False}
    data["cues"].append({**copy.deepcopy(data["cues"][0]), "cue_id": "second"})
    result = execute_request(data).to_dict()
    assert len(result["cues"]) == 2 and all(p["status"] == "failed" for p in result["cues"])
    for p in result["cues"]:
        details = p["error"]["details"]
        assert details["group_id"] == "caption" and details["layer_id"]
        assert details["minimum_factor"] >= 0.4
        assert details["cue_id"] == p["cue_id"]
    assert not (tmp_path / "output with spaces").exists()


def test_coordinated_shrink_keeps_size_ratios_and_readable_minima(tmp_path):
    data = group_request(tmp_path)
    data["caption_groups"][0].update(region=[0.2, 0.4, 0.8, 0.62], gap=0.3)
    result = execute_request(data).to_dict()
    assert result["status"] == "complete", result
    plans = [p for p in result["cues"][0]["layers"] if p["layer"]["kind"] == "text"]
    assert all(p["font_size"] >= p["layer"]["min_font_size"] for p in plans)
    assert plans[0]["font_size"] / plans[1]["font_size"] == pytest.approx(30 / 16, abs=0.02)


def test_explicit_scale_basis_and_legacy_default_geometry():
    font = str(asset_path("fonts", "multilingual_fonts", "am.ttf"))
    layer = Layer("translation", "Caption", font, direction="ltr", region=(0.05, 0.1, 0.95, 0.9))
    scene = Scene(1920, 1080, (layer,))
    old = plan_scene(scene)[0]
    explicit = plan_scene(replace(scene, layers=(replace(layer, scale_basis="width", anchor_mode="baseline"),)))[0]
    assert old == explicit
    short = plan_scene(replace(scene, layers=(replace(layer, scale_basis="short_side"),)))[0]
    fixed = plan_scene(replace(scene, layers=(replace(layer, scale_basis="pixels"),)))[0]
    assert old.font_size == 100 and short.font_size == 56 and fixed.font_size == 30


def test_block_anchor_includes_panel_and_common_size_helper(tmp_path):
    from quran_image_generator.api import common_size_suggestion

    data = fixture_request(tmp_path, "layout")
    data["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "provenance": {},
                       "styles": {"arabic": {"anchor": [0.5, 0.8], "anchor_mode": "block_bottom", "region": [0.05, 0.1, 0.95, 0.9], "panel": {"opacity": 0.6}}}}
    result = execute_request(data).to_dict()
    assert result["status"] == "complete", result
    assert result["cues"][0]["layers"][0]["bounds"][3] == round(0.8 * 1024)
    suggestion = common_size_suggestion(result)
    assert suggestion["reference_sizes"]["arabic"] == 30
    assert suggestion["requires_revalidation"] and not suggestion["failed_cues"]


def test_flow_crop_recomposition_contains_every_child_and_panel(tmp_path):
    from quran_image_generator.caption_editor import compose_caption

    data = group_request(tmp_path)
    full = execute_request(data).to_dict()
    data["cropped"] = True
    cropped = execute_request(data).to_dict()
    with compose_caption(full, 0, (576, 1024)) as a, compose_caption(cropped, 0, (576, 1024)) as b:
        assert a.tobytes() == b.tobytes()
    for plan in full["cues"][0]["layers"]:
        record = next(a for a in full["assets"] if a["asset_id"] == plan["asset_id"])
        with Image.open(Path(full["job_directory"]) / record["path"]) as image:
            bounds = image.getbbox()
        assert all(a >= p - 1 for a, p in zip(bounds[:2], plan["bounds"][:2], strict=True))
        assert all(a <= p + 1 for a, p in zip(bounds[2:], plan["bounds"][2:], strict=True))
