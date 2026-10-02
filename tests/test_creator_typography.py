"""Portable coverage of decoration and symbol font branding."""

from dataclasses import replace

import pytest
from PIL import Image
from test_api import fixture_request

from quran_image_generator.api import execute_request
from quran_image_generator.creator_assets import matched_creator_configuration
from quran_image_generator.excerpts import ExcerptRequest, select_excerpt
from quran_image_generator.profiles import decorate_excerpt
from quran_image_generator.references import ReferenceError, SourceSpan
from quran_image_generator.resources import asset_path
from quran_image_generator.scenes import (
    caption_scene,
    checked_asset,
    plan_scene,
    render_layer,
)


def test_custom_ornaments_and_regular_numerals_preserve_source():
    excerpt = select_excerpt(ExcerptRequest("end", (SourceSpan(39, 30, 4, 4),)))
    scene = caption_scene(excerpt)
    arabic = replace(
        scene.layers[0],
        quote_open="{",
        quote_close="}",
        numeral_system="latin",
        marker_prefix="(",
        marker_suffix=")",
        suffix_spacing=5,
    )
    scene = decorate_excerpt(excerpt, replace(scene, layers=(arabic,)))
    assert scene.layers[0].text == "{ " + excerpt.text + " }"
    assert scene.layers[0].suffix == "(30)"
    assert "{" not in excerpt.text and "30" not in excerpt.text
    # Decoration selection is independent from verse-number encoding.
    scene = decorate_excerpt(
        excerpt,
        replace(scene, layers=(replace(arabic, numeral_system="arabic_indic"),)),
    )
    assert scene.layers[0].suffix == "(٣٠)"


def test_symbol_font_logo_is_persistent_and_hash_pinned(tmp_path):
    request = fixture_request(tmp_path)
    font = str(asset_path("fonts", "multilingual_fonts", "am.ttf"))
    request["assets"] = {
        "logo": {
            "path": font,
            "sha256": checked_asset(font),
            "glyph": "Q",
            "license": "fixture only",
            "attribution": "Bundled font test",
        }
    }
    result = execute_request(request).to_dict()
    assert result["status"] == "complete"
    logo = next(asset for asset in result["assets"] if "logo" in asset["roles"])
    assert logo["persistent"] and logo["font_sha256"] == checked_asset(font)
    with Image.open(
        __import__("pathlib").Path(result["job_directory"]) / logo["path"]
    ) as image:
        assert image.getbbox() is not None and image.getpixel((0, 0))[3] == 0
    layer = next(
        plan["layer"]
        for plan in result["cues"][0]["layers"]
        if plan["layer"]["role"] == "logo"
    )
    assert layer["text"] == "Q" and layer["image"] == ""
    request["assets"]["arabic"] = request["assets"]["logo"]
    assert execute_request(request).payload["error"]["code"] == "invalid_request"


def test_fractional_reference_size_survives_layout_and_shrink():
    excerpt = select_excerpt(ExcerptRequest("a", (SourceSpan(31, 9, 1, 5),)))
    scene = caption_scene(excerpt)
    scene = replace(
        scene, layers=(replace(scene.layers[0], font_size=29.25, fit="shrink"),)
    )
    plan = plan_scene(scene)[0]
    assert plan.font_size == 29.25
    assert plan.lines and plan.bounds


@pytest.mark.parametrize("width,height", [(576, 1024), (1080, 1920)])
def test_horizontal_adjustment_keeps_shaped_line_and_fit_bounds(
    tmp_path, width, height
):
    excerpt = select_excerpt(ExcerptRequest("a", (SourceSpan(31, 9, 1, 5),)))
    scene = caption_scene(excerpt, width=width, height=height)
    layer = replace(
        scene.layers[0], font_size=25.25, horizontal_scale=1.14, fit="shrink"
    )
    scene = replace(scene, layers=(layer,))
    plan = plan_scene(scene)[0]
    assert plan.lines[0][0] == excerpt.text
    asset = render_layer(scene, plan, tmp_path / "scaled.png", cropped=True)
    assert asset.bounds
    assert all(
        a >= b - 1 for a, b in zip(asset.bounds[:2], plan.bounds[:2], strict=True)
    )
    assert all(
        a <= b + 1 for a, b in zip(asset.bounds[2:], plan.bounds[2:], strict=True)
    )
    with Image.open(tmp_path / "scaled.png") as image:
        assert image.getchannel("A").getextrema() == (0, 255)


def test_mixed_decoration_font_handles_wrapping_and_multiple_verse_endings(tmp_path):
    request = fixture_request(tmp_path)
    font = str(asset_path("fonts", "multilingual_fonts", "am.ttf"))
    request["assets"] = {
        "decorations": {
            "path": font,
            "sha256": checked_asset(font),
            "license": "fixture only",
            "attribution": "Test decoration font",
        }
    }
    request.update(quotations=True, verse_numbers=True)
    request["profile"] = {
        "id": "mixed-font-test",
        "revision": "1",
        "approval": "approved",
        "styles": {
            "arabic": {
                "quote_open": "(",
                "quote_close": ")",
                "numeral_system": "latin",
                "marker_prefix": "(",
                "marker_suffix": ")",
                "suffix_offset": -4,
            }
        },
        "provenance": {"purpose": "test"},
    }
    for cue in request["cues"]:
        cue["spans"] = [
            {"surah": 31, "ayah": 9, "word_start": 6, "word_end": 8},
            {"surah": 31, "ayah": 10, "word_start": 1, "word_end": 1},
        ]
    result = execute_request(request).to_dict()
    assert result["status"] == "complete"
    layer = result["cues"][0]["layers"][0]
    assert layer["layer"]["inline_markers"] == ["(9)"]
    assert layer["layer"]["ornaments"] and len(layer["ornament_positions"]) == 2
    with Image.open(
        __import__("pathlib").Path(result["job_directory"])
        / result["assets"][0]["path"]
    ) as image:
        assert image.getbbox() is not None


def test_creator_factory_pins_three_discovered_fonts(tmp_path, monkeypatch):
    from pathlib import Path

    import quran_image_generator.creator_assets as creator

    font = asset_path("fonts", "multilingual_fonts", "am.ttf")
    looked_up = []

    def lookup(directory, digest):
        looked_up.append(digest)
        return font

    class Names:
        def getDebugName(self, index):
            return {1: "Arial", 2: "Regular"}[index]

    class TestFont:
        def __enter__(self):
            return {"name": Names()}

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(creator, "_find_font", lookup)
    monkeypatch.setattr(creator, "TTFont", lambda path: TestFont())
    config = creator.matched_creator_configuration(tmp_path, Path(font))
    assert set(looked_up) == {
        creator.ME_QURAN_SHA256,
        creator.ALI_SHA256,
        creator.SURAH_SHA256,
    }
    assert config["assets"]["logo"]["glyph"] == "y"
    assert config["assets"]["arabic"]["sha256"] == creator.ME_QURAN_SHA256
    assert config["assets"]["decorations"]["sha256"] == creator.ALI_SHA256
    assert config["profile"]["approval"] == "needs_review"


def test_missing_creator_font_never_silently_falls_back(tmp_path):
    with pytest.raises(ReferenceError) as error:
        matched_creator_configuration(tmp_path, asset_path("fonts", "quran_font.ttf"))
    assert error.value.code == "missing_font"


def test_changed_decoration_font_prevents_job_publication(tmp_path, monkeypatch):
    import shutil

    import quran_image_generator.api as api

    font = tmp_path / "decoration.ttf"
    shutil.copyfile(asset_path("fonts", "multilingual_fonts", "am.ttf"), font)
    request = fixture_request(tmp_path)
    request["assets"] = {
        "decorations": {
            "path": str(font),
            "sha256": checked_asset(str(font)),
            "license": "test only",
            "attribution": "fixture",
        }
    }
    original = api.render_layer

    def mutate_after_render(*args, **kwargs):
        asset = original(*args, **kwargs)
        font.write_bytes(font.read_bytes() + b"changed")
        return asset

    monkeypatch.setattr(api, "render_layer", mutate_after_render)
    result = api.execute_request(request).to_dict()
    assert result["status"] == "failed" and result["assets"] == []
    assert result["error"]["code"] == "changed_asset"
    assert not list((tmp_path / "output with spaces").glob("job-*"))
