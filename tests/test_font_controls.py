from dataclasses import replace

import pytest
from fontTools.ttLib import TTCollection, TTFont
from PIL import Image
from test_api import fixture_request

from quran_image_generator.api import execute_request, runtime_identity
from quran_image_generator.font_controls import FontWorkspace, inspect_font
from quran_image_generator.references import ReferenceError
from quran_image_generator.resources import asset_path
from quran_image_generator.scenes import (
    Layer,
    Scene,
    checked_asset,
    plan_scene,
    render_layer,
)


def latin_font():
    return str(asset_path("fonts", "multilingual_fonts", "am.ttf"))


def font_selector(path):
    return {"path": str(path), "sha256": checked_asset(str(path)), "license": "fixture terms", "attribution": "Bundled font test"}


def test_inspect_real_variable_font_coverage_metrics_and_hash():
    info = inspect_font(latin_font(), text="café e\u0301", role="translation", font_size=30)
    assert info["family"] and info["units_per_em"] > 0
    assert {a["tag"] for a in info["variable_axes"]} == {"wght", "wdth"}
    assert info["coverage"]["complete"]
    assert info["metrics"]["ascender_pixels"] > 0
    missing = inspect_font(latin_font(), text="hello بسم")
    assert not missing["coverage"]["complete"] and "بسم" in missing["coverage"]["missing_words"]
    with pytest.raises(ReferenceError) as error:
        inspect_font(latin_font(), sha256="0" * 64)
    assert error.value.code == "changed_asset"


def test_axis_instances_change_real_metrics_pixels_and_repeat_deterministically(tmp_path):
    layer = Layer("translation", "Wide caption office", latin_font(), direction="ltr")
    assets, widths, hashes = [], [], []
    for index, axes in enumerate(({"wght": 100, "wdth": 62.5}, {"wght": 900, "wdth": 100}, {"wght": 100, "wdth": 62.5})):
        with FontWorkspace() as fonts:
            scene = fonts.prepare_scene(Scene(576, 1024, (replace(layer, variation_axes=axes),)))
            plan = plan_scene(scene)[0]
            asset = render_layer(scene, plan, tmp_path / f"axes-{index}.png", cropped=True)
            assets.append(asset.sha256)
            widths.append(asset.width)
            hashes.append(plan.font_info["derived_sha256"])
            assert plan.font_info["effective"]["effective_axes"] == axes
            assert all(a >= b - 1 for a, b in zip(asset.bounds[:2], plan.bounds[:2], strict=True))
            assert all(a <= b + 1 for a, b in zip(asset.bounds[2:], plan.bounds[2:], strict=True))
    assert widths[0] < widths[1]
    assert assets[0] != assets[1] and assets[0] == assets[2]
    assert hashes[0] == hashes[2]


def test_axis_failures_have_exact_json_field_paths(tmp_path):
    data = fixture_request(tmp_path, "inspect")
    data["assets"] = {"arabic": font_selector(latin_font())}
    for axes, code, suffix in (({"ZZZZ": 1}, "unknown_font_axis", "ZZZZ"), ({"wght": 1000}, "invalid_font_axis", "wght")):
        data["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "provenance": {}, "styles": {"arabic": {"variation_axes": axes}}}
        result = execute_request(data).to_dict()
        error = result["cues"][0]["error"]
        assert error["code"] == code
        assert error["details"]["path"] == "/profile/styles/arabic/variation_axes/" + suffix


def test_collection_face_is_selected_and_materialized(tmp_path):
    path = tmp_path / "faces.ttc"
    collection = TTCollection()
    collection.fonts = [TTFont(latin_font()), TTFont(str(asset_path("fonts", "multilingual_fonts", "hi.ttf")))]
    collection.save(path)
    collection.close()
    info = inspect_font(path, font_face=1, text="क")
    assert len(info["collection_faces"]) == 2
    assert info["coverage"]["complete"]
    layer = Layer("translation", "क", str(path), direction="ltr", font_face=1)
    with FontWorkspace() as fonts:
        scene = fonts.prepare_scene(Scene(576, 1024, (layer,)))
        plan = plan_scene(scene)[0]
        asset = render_layer(scene, plan, tmp_path / "collection.png")
        assert asset.bounds
        assert plan.font_info["effective"]["font_face"] == 1
    with pytest.raises(ReferenceError) as error:
        inspect_font(latin_font(), font_face=1)
    assert error.value.code == "invalid_font_face"


def test_explicit_fallback_keeps_complete_layer_and_rechecks_all_pins(tmp_path):
    primary = str(asset_path("fonts", "quran_font.ttf"))
    copied = tmp_path / "fallback.ttf"
    copied.write_bytes(__import__("pathlib").Path(latin_font()).read_bytes())
    layer = Layer("translation", "café e\u0301", primary, direction="ltr", font_fallbacks=(font_selector(copied),))
    with FontWorkspace() as fonts:
        scene = fonts.prepare_scene(Scene(576, 1024, (layer,)))
        plan = plan_scene(scene)[0]
        assert plan.font_info["fallback_used"]
        assert plan.font_info["effective"]["sha256"] == checked_asset(str(copied))
        assert plan.lines[0][0] == layer.text
        render_layer(scene, plan, tmp_path / "fallback.png")
        copied.write_bytes(copied.read_bytes() + b"changed")
        with pytest.raises(ReferenceError) as error:
            render_layer(scene, plan, tmp_path / "must-not-render.png")
        assert error.value.code == "changed_asset"


def test_combining_mark_cannot_use_an_isolated_fallback(tmp_path):
    primary, fallback = tmp_path / "base.ttf", tmp_path / "marks.ttf"
    with TTFont(latin_font()) as f:
        for table in f["cmap"].tables:
            table.cmap.pop(0x301, None)
        f.save(primary)
    with TTFont(latin_font()) as f:
        for table in f["cmap"].tables:
            table.cmap.pop(ord("e"), None)
        f.save(fallback)
    layer = Layer("translation", "e\u0301", str(primary), direction="ltr", font_fallbacks=(font_selector(fallback),))
    with FontWorkspace() as fonts, pytest.raises(ReferenceError) as error:
        fonts.prepare_scene(Scene(576, 1024, (layer,)))
    assert error.value.code == "missing_glyph"


def test_required_arabic_features_and_backend_limitations(tmp_path):
    data = fixture_request(tmp_path, "layout")
    data["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "provenance": {}, "styles": {"arabic": {"font_features": ["-rlig"]}}}
    result = execute_request(data).to_dict()
    assert result["cues"][0]["error"]["code"] == "required_shaping_feature"
    assert result["cues"][0]["error"]["details"]["path"] == "/profile/styles/arabic/font_features/0"
    with FontWorkspace() as fonts:
        scene = fonts.prepare_scene(Scene(576, 1024, (Layer("translation", "office", latin_font(), direction="ltr", font_features=("kern",), font_language="en"),)))
        if not runtime_identity()["pillow_raqm"]:
            with pytest.raises(ReferenceError) as error:
                plan_scene(scene)
            assert error.value.code == "unsupported_shaping_option"
        else:
            plan = plan_scene(scene)[0]
            assert plan.typography["backend"] == "pillow_raqm"
            assert plan.font_info["features"] == ("kern",)
            asset = render_layer(scene, plan, tmp_path / "features.png")
            with Image.open(tmp_path / "features.png") as image:
                assert image.getbbox() == asset.bounds


def test_font_inspection_operation_creates_no_output(tmp_path):
    data = {"schema_version": 1, "request_id": "fonts", "operation": "inspect_fonts",
            "assets": {"translation": font_selector(latin_font())}, "font_samples": {"translation": "office"},
            "output_directory": str(tmp_path / "output")}
    result = execute_request(data).to_dict()
    assert result["status"] == "complete"
    assert result["font_inspection"]["translation"]["license"] == "fixture terms"
    assert not (tmp_path / "output").exists()


def test_inspection_cache_does_not_share_mutable_metadata_or_ignore_pins():
    info = inspect_font(latin_font(), text="hello")
    info["effective_axes"]["wght"] = 999
    info["available_features"].clear()
    again = inspect_font(latin_font(), text="hello")
    assert again["effective_axes"]["wght"] != 999
    assert again["available_features"]
    with pytest.raises(ReferenceError) as error:
        inspect_font(latin_font(), sha256="0" * 64)
    assert error.value.code == "changed_asset"


def test_font_inspection_canvas_units_and_axis_diagnostics(tmp_path):
    data = {"schema_version": 1, "request_id": "fonts", "operation": "inspect_fonts", "canvas": {"width": 1152, "height": 1024},
            "assets": {"translation": font_selector(latin_font())}, "font_samples": {"translation": "office"}}
    assert execute_request(data).to_dict()["font_inspection"]["translation"]["font_size_output_pixels"] == 32
    data["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "provenance": {}, "styles": {"translation": {"variation_axes": {"wght": 999}}}}
    error = execute_request(data).to_dict()["error"]
    assert error["details"]["path"] == "/profile/styles/translation/variation_axes/wght"
