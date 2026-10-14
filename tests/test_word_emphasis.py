"""Source-occurrence paint states must preserve the approved static raster."""

import hashlib
import json
import runpy
from dataclasses import asdict
from pathlib import Path

import jsonschema
import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.ttLib import TTCollection, TTFont
from image_helpers import rgba_pixels
from PIL import Image, ImageChops, ImageDraw, ImageFont
from test_api import fixture_request
from test_font_controls import font_selector
from test_group_layout import group_request

from quran_image_generator.api import (
    capabilities,
    common_size_suggestion,
    execute_request,
    style_descriptor,
)
from quran_image_generator.caption_editor import CaptionDocument, compose_caption
from quran_image_generator.contract_schema import REQUEST_SCHEMA, RESPONSE_SCHEMA
from quran_image_generator.excerpts import ExcerptRequest, select_excerpt
from quran_image_generator.references import ReferenceError, SourceSpan
from quran_image_generator.render_cache import CaptionRenderCache
from quran_image_generator.requests import (
    BatchRequest,
    CueRequest,
    WordSelection,
    WordState,
)
from quran_image_generator.resources import asset_path
from quran_image_generator.word_emphasis import (
    compose_word_state,
    interpolate_word_states,
)

FONTS = Path(__file__).parent / "fixtures" / "fonts"


def request(
    tmp_path, *, spans=None, layout="legacy", style=None, operation="render_batch"
):
    data = fixture_request(tmp_path, operation)
    data["cues"] = [
        {"cue_id": "words", "spans": spans or [asdict(SourceSpan(31, 9, 1, 8))]}
    ]
    data.update(quotations=True, verse_numbers=True, cropped=True)
    data["profile"] = {
        "id": "plain",
        "revision": "1",
        "approval": "approved",
        "provenance": {},
        "styles": {
            "arabic": {
                "decoration_layout": layout,
                "max_lines": 8,
                "region": [0.05, 0.05, 0.95, 0.95],
                **(style or {}),
            }
        },
    }
    return data


def checked(data, **kwargs):
    result = execute_request(data, **kwargs).to_dict()
    assert result["status"] == "complete", result.get("error") or result["cues"]
    jsonschema.validate(result, RESPONSE_SCHEMA)
    return result


def same(a, b):
    assert a.size == b.size and a.mode == b.mode
    assert a.tobytes() == b.tobytes()


def assert_changes_inside(a, b, units):
    # Compare RGB too: Pillow's RGBA getbbox defaults to alpha on newer versions.
    difference = ImageChops.difference(a, b).convert("RGB")
    assert difference.getbbox()
    permitted = Image.new("L", a.size)
    draw = ImageDraw.Draw(permitted)
    for unit in units:
        for part in unit["parts"]:
            left, top, right, bottom = part["ink_bounds"]
            draw.rectangle((left, top, right - 1, bottom - 1), fill=255)
    assert not ImageChops.multiply(
        difference.convert("L"), ImageChops.invert(permitted)
    ).getbbox()


@pytest.mark.parametrize("layout", ["legacy", "elements"])
@pytest.mark.parametrize(
    "font", ["madina", "ScheherazadeNew-Regular.ttf", "NotoNaskhArabic.ttf"]
)
def test_neutral_exact_shaping_marks_spacing_scaling_effects_and_fractional_alpha(
    tmp_path, layout, font
):
    data = request(
        tmp_path,
        layout=layout,
        style={
            "font_size": 30.5,
            "word_spacing": 0.23,
            "horizontal_scale": 1.12,
            "outline_width": 0.7,
            "outline_color": "#004466",
            "shadow_blur": 1,
            "shadow_offset": [1, 2],
            "shadow_opacity": 0.3,
            "opacity": 0.73,
            "fit": "shrink",
        },
    )
    if font != "madina":
        data["assets"] = {"arabic": font_selector(FONTS / font)}
    baseline = checked(data)
    data["word_emphasis"] = {}
    data["cues"][0]["word_states"] = [
        {"state_id": "all"},
        {"state_id": "none", "default_weight": 0},
    ]
    result = checked(data)
    cue = result["cues"][0]
    assert cue["arabic"] == baseline["cues"][0]["arabic"]
    assert cue["source_spans"] == baseline["cues"][0]["source_spans"]
    assert cue["layers"] == baseline["cues"][0]["layers"]
    with (
        compose_caption(baseline, 0, (576, 1024)) as original,
        compose_word_state(result, 0, "all") as all_active,
        compose_word_state(result, 0, "none") as dimmed,
    ):
        same(original, all_active)
        same(original.getchannel("A"), dimmed.getchannel("A"))
        assert_changes_inside(all_active, dimmed, cue["word_emphasis"]["units"])
        assert any(0 < value < 255 for value in original.getchannel("A").tobytes())
        with interpolate_word_states(dimmed, all_active, 0.4) as fading:
            same(fading.getchannel("A"), original.getchannel("A"))
    # Force a real paint variant with identical colors, bypassing neutral asset reuse.
    data["word_emphasis"] = {"active_color": "#FFFFFF", "inactive_color": "#FFFFFF"}
    data["cues"][0]["word_states"] = [{"state_id": "same-paint", "default_weight": 0.4}]
    repaint = checked(data)
    with (
        compose_caption(baseline, 0, (576, 1024)) as original,
        compose_word_state(repaint, 0, "same-paint") as painted,
    ):
        same(original, painted)
    assert all(
        part["mask_font_sha256"]
        for unit in cue["word_emphasis"]["units"]
        for part in unit["parts"]
    )


@pytest.mark.parametrize("layout", ["legacy", "elements"])
def test_current_cumulative_and_repeat_occurrences_change_only_the_selected_word(
    tmp_path, layout
):
    span = asdict(SourceSpan(31, 9, 6, 8))
    data = request(
        tmp_path, spans=[span, span, asdict(SourceSpan(112, 1, 1, 4))], layout=layout
    )
    data["word_emphasis"] = {"inactive_color": "#223344", "active_color": "#EEDDCC"}
    data["cues"][0]["line_breaks"] = [
        {"span_occurrence": 1, "source_word": 6, "mode": "forced"}
    ]
    data["cues"][0]["word_states"] = [
        {"state_id": "none", "default_weight": 0},
        {
            "state_id": "current",
            "default_weight": 0,
            "words": [{"span_occurrence": 1, "source_word": 7, "weight": 1}],
        },
        {
            "state_id": "cumulative",
            "default_weight": 0,
            "words": [
                {"span_occurrence": 1, "source_word": word, "weight": 1}
                for word in (6, 7)
            ],
        },
    ]
    result = checked(data)
    units = result["cues"][0]["word_emphasis"]["units"]
    members = [member for unit in units for member in unit["members"]]
    assert (
        len(members) == 10
        and len({(m["span_occurrence"], m["source_word"]) for m in members}) == 10
    )
    assert all(m["cue_id"] == "words" for m in members)
    assert len({part["line_index"] for unit in units for part in unit["parts"]}) > 1
    with (
        compose_word_state(result, 0, "none") as none,
        compose_word_state(result, 0, "current") as current,
        compose_word_state(result, 0, "cumulative") as cumulative,
    ):

        def selected(word):
            return [
                unit
                for unit in units
                if any(
                    m["span_occurrence"] == 1 and m["source_word"] == word
                    for m in unit["members"]
                )
            ]

        assert_changes_inside(none, current, selected(7))
        assert_changes_inside(current, cumulative, selected(6))
        same(none.getchannel("A"), current.getchannel("A"))


def test_joined_source_display_group_is_explicit_and_cannot_be_split(tmp_path):
    data = request(
        tmp_path, spans=[asdict(SourceSpan(5, 72, 13, 15))], layout="elements"
    )
    data["word_emphasis"] = {}
    metadata = checked({**data, "operation": "layout"})["cues"][0]["word_emphasis"]
    joined = next(unit for unit in metadata["units"] if len(unit["members"]) > 1)
    assert [m["source_word"] for m in joined["members"]] == [13, 14]
    assert joined["atomic"] and "source_display_group" in joined["atomic_reasons"]
    data["cues"][0]["word_states"] = [
        {
            "state_id": "split",
            "default_weight": 0,
            "words": [{"span_occurrence": 0, "source_word": 13, "weight": 1}],
        }
    ]
    failed = execute_request(data).to_dict()
    error = failed["cues"][0]["error"]
    assert error["code"] == "atomic_word_split"
    assert error["details"]["path"] == "/cues/0/word_states/0/words"
    assert error["details"]["members"] == joined["members"]
    assert not (tmp_path / "output with spaces").exists()
    data["cues"][0]["word_states"][0]["words"].append(
        {"span_occurrence": 0, "source_word": 14, "weight": 1}
    )
    assert (
        checked(data)["cues"][0]["word_emphasis"]["states"][0]["weights"][0]["weight"]
        == 1
    )


@pytest.mark.parametrize("mode", ["fill", "background", "both"])
def test_background_geometry_weights_offsets_and_empty_state(tmp_path, mode):
    data = request(
        tmp_path, layout="elements", style={"outline_width": 0, "shadow_opacity": 0}
    )
    baseline = checked(data)
    data["word_emphasis"] = {
        "mode": mode,
        "background": {
            "color": "#00FF00",
            "opacity": 0.4,
            "padding": [2.5, 3.5],
            "corner_radius": 0,
            "unit": "output_pixels",
        },
    }
    data["cues"][0]["word_states"] = [
        {"state_id": "none", "default_weight": 0},
        {
            "state_id": "half",
            "default_weight": 0,
            "words": [{"span_occurrence": 0, "source_word": 2, "weight": 0.5}],
        },
        {
            "state_id": "one",
            "default_weight": 0,
            "words": [{"span_occurrence": 0, "source_word": 2, "weight": 1}],
        },
    ]
    result = checked(data)
    unit = next(
        unit
        for unit in result["cues"][0]["word_emphasis"]["units"]
        if unit["members"][0]["source_word"] == 2
    )
    for part, box in zip(unit["parts"], unit["backgrounds"], strict=True):
        a, b, c, d = part["ink_bounds"]
        assert box["rect"] == [a - 3, b - 4, c + 3, d + 4]
    with (
        compose_word_state(result, 0, "none") as none,
        compose_word_state(result, 0, "half") as half,
        compose_word_state(result, 0, "one") as one,
    ):
        if mode == "background":
            with compose_caption(baseline, 0, (576, 1024)) as original:
                same(none, original)
        if mode == "fill":
            same(one.getchannel("A"), none.getchannel("A"))
        else:
            left, top, _, _ = unit["backgrounds"][0]["rect"]
            assert half.getpixel((left, top)) == (0, 255, 0, 51)
            assert one.getpixel((left, top)) == (0, 255, 0, 102)


def test_independent_decoration_colors_panels_translations_titles_labels_unchanged(
    tmp_path,
):
    data = group_request(tmp_path)
    data.update(titles=True, quotations=True, verse_numbers=True, cropped=True)
    data["profile"] = {
        "id": "plain",
        "revision": "1",
        "approval": "approved",
        "provenance": {},
        "styles": {
            "arabic": {
                "decoration_layout": "elements",
                "quotation_style": {"color": "#00CCFF"},
                "marker_style": {"color": "#FFD700"},
            }
        },
    }
    baseline = checked(data)
    data["word_emphasis"] = {}
    data["cues"][0]["word_states"] = [
        {"state_id": "all"},
        {"state_id": "none", "default_weight": 0},
    ]
    result = checked(data)
    layers = result["cues"][0]["layers"]
    assert layers == baseline["cues"][0]["layers"]
    state = result["cues"][0]["word_emphasis"]["states"][1]
    assert [
        a
        for a in state["asset_ids"]
        if a != next(a["asset_id"] for a in layers if a["layer"]["role"] == "arabic")
    ] != []
    for before, after in zip(
        baseline["cues"][0]["asset_ids"], state["asset_ids"], strict=True
    ):
        if before != next(
            item["asset_id"] for item in layers if item["layer"]["role"] == "arabic"
        ):
            assert before == after
    with (
        compose_word_state(result, 0, "all") as all_active,
        compose_word_state(result, 0, "none") as none,
    ):
        # Exact ornament pixels survive; effects use the same alpha and paint order.
        for rgb in ((0, 204, 255), (255, 215, 0)):
            original = bytes(
                p[3] if p[:3] == rgb else 0 for p in rgba_pixels(all_active)
            )
            dimmed = bytes(p[3] if p[:3] == rgb else 0 for p in rgba_pixels(none))
            assert original == dimmed


@pytest.mark.parametrize("cropped", [False, True])
def test_public_typed_json_editor_roundtrip_checksums_and_composition(
    tmp_path, cropped
):
    cue = CueRequest(
        "first",
        (SourceSpan(31, 9, 1, 5),),
        word_states=(
            WordState("all"),
            WordState("current", 0, (WordSelection(0, 2, 1),)),
        ),
    )
    batch = BatchRequest(
        "typed",
        (cue,),
        operation="render_batch",
        output_directory=str(tmp_path),
        cropped=cropped,
        word_emphasis={},
    )
    typed = batch.to_request()
    serialized = json.loads(json.dumps(typed.to_dict()))
    jsonschema.validate(serialized, REQUEST_SCHEMA)
    document = CaptionDocument(serialized)
    same_request = document.request().to_dict()
    assert (
        same_request["word_emphasis"] == {}
        and same_request["cues"][0]["word_states"]
        == serialized["cues"][0]["word_states"]
    )
    response = execute_request(typed)
    data = response.to_dict()
    assert data["status"] == "complete", data
    jsonschema.validate(data, RESPONSE_SCHEMA)
    with (
        compose_word_state(response, 0, "all") as a,
        compose_word_state(json.loads(json.dumps(data)), 0, "all") as b,
        compose_caption(data, 0, (576, 1024)) as static,
    ):
        same(a, b)
        same(a, static)
    for asset in data["assets"]:
        path = Path(data["job_directory"]) / asset["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]
        assert asset["alpha_mode"] == "straight" and asset["color_space"] == "sRGB"
        if cropped:
            assert asset["offset"] == asset["bounds"][:2]
    variant = next(
        asset
        for asset in data["assets"]
        if asset["asset_id"]
        in data["cues"][0]["word_emphasis"]["states"][1]["asset_ids"]
    )
    (Path(data["job_directory"]) / variant["path"]).write_bytes(b"changed")
    with pytest.raises(ReferenceError, match="changed") as failure:
        compose_word_state(data, 0, "current")
    assert failure.value.code == "changed_asset"


def test_discovery_output_free_operations_and_default_opt_in(tmp_path):
    descriptor = capabilities()["word_emphasis"]
    assert capabilities()["word_highlighting"] and descriptor["supported"]
    assert (
        descriptor["version"] == 1
        and descriptor["representation"] == "selection_state_variants"
    )
    assert style_descriptor()["word_emphasis"] == descriptor
    assert capabilities("imagemagick")["word_highlighting"] is False
    assert not capabilities("imagemagick")["word_emphasis"]["supported"]
    data = request(tmp_path, operation="layout")
    assert "word_emphasis" not in checked(data)["cues"][0]
    data["word_emphasis"] = {}
    for operation in ("layout", "validate", "inspect", "preflight"):
        result = checked(
            {
                key: value
                for key, value in {**data, "operation": operation}.items()
                if key != "output_directory"
            }
        )
        assert result["assets"] == []
        assert result["cues"][0]["word_emphasis"]["states"][0]["state_id"] == "all"
        assert not (tmp_path / "output with spaces").exists()


@pytest.mark.parametrize(
    "states,code,path",
    [
        (
            [{"state_id": "x"}, {"state_id": "x"}],
            "duplicate_word_state",
            "/cues/0/word_states/1/state_id",
        ),
        (
            [
                {
                    "state_id": "x",
                    "words": [{"span_occurrence": 1, "source_word": 1, "weight": 1}],
                }
            ],
            "invalid_word_selection",
            "/cues/0/word_states/0/words/0",
        ),
        (
            [
                {
                    "state_id": "x",
                    "words": [{"span_occurrence": 0, "source_word": 1, "weight": 1}]
                    * 2,
                }
            ],
            "duplicate_word_selection",
            "/cues/0/word_states/0/words/1",
        ),
    ],
)
def test_exact_selector_errors_before_publication(tmp_path, states, code, path):
    data = request(tmp_path)
    data["word_emphasis"] = {}
    data["cues"][0]["word_states"] = states
    result = execute_request(data).to_dict()
    assert result["status"] == "failed" and result["assets"] == []
    assert result["cues"][0]["error"]["code"] == code
    assert result["cues"][0]["error"]["details"]["path"] == path
    assert not (tmp_path / "output with spaces").exists()


def test_unsupported_backend_missing_configuration_and_background_overflow(tmp_path):
    data = request(tmp_path, operation="layout")
    data["cues"][0]["word_states"] = [{"state_id": "all"}]
    assert (
        execute_request(data).payload["cues"][0]["error"]["code"]
        == "invalid_word_selection"
    )
    data["word_emphasis"] = {}
    data["render_backend"] = "imagemagick"
    assert (
        execute_request(data).payload["cues"][0]["error"]["code"]
        == "unsupported_word_emphasis_backend"
    )
    data["render_backend"] = "pillow"
    data["word_emphasis"] = {"mode": "background", "active_color": "#FFFFFF"}
    assert (
        execute_request(data).payload["cues"][0]["error"]["code"]
        == "unsupported_word_emphasis_option"
    )
    data["word_emphasis"] = {"mode": "background", "background": {"padding": [64, 64]}}
    assert (
        execute_request(data).payload["cues"][0]["error"]["code"]
        == "word_background_overflow"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"active_color": "red"},
        {"background": {"opacity": 2}},
        {"background": {"padding": [-1, 0]}},
    ],
)
def test_strict_schema_rejects_invalid_paint_options(tmp_path, change):
    data = request(tmp_path)
    data["word_emphasis"] = change
    assert execute_request(data).payload["error"]["code"] == "invalid_request"


def test_repeated_cues_reuse_content_assets_but_keep_source_identity(tmp_path):
    data = fixture_request(tmp_path)
    data["word_emphasis"] = {}
    for cue in data["cues"]:
        cue["word_states"] = [
            {"state_id": "all"},
            {"state_id": "none", "default_weight": 0},
        ]
    first = checked(data)
    assert len(first["assets"]) == 2
    a, b = first["cues"]
    assert a["word_emphasis"]["layout_id"] == b["word_emphasis"]["layout_id"]
    assert a["word_emphasis"]["states"] == b["word_emphasis"]["states"]
    assert a["word_emphasis"]["units"][0]["members"][0]["cue_id"] == "a"
    assert b["word_emphasis"]["units"][0]["members"][0]["cue_id"] == "b"


def test_working_coverage_fallback_variable_axes_faces_and_features(tmp_path):
    collection = TTCollection()
    collection.fonts = [
        TTFont(str(asset_path("fonts", "multilingual_fonts", "am.ttf"))),
        TTFont(FONTS / "NotoNaskhArabic.ttf"),
    ]
    font = tmp_path / "arabic.ttc"
    collection.save(font)
    collection.close()
    data = request(
        tmp_path,
        layout="elements",
        style={
            "font_face": 1,
            "variation_axes": {"wght": 600},
            "font_features": ["kern"],
            "font_language": "ar",
        },
    )
    data["assets"] = {"arabic": font_selector(font)}
    baseline = checked(data)
    data["word_emphasis"] = {}
    emphasized = checked(data)
    with (
        compose_caption(baseline, 0, (576, 1024)) as original,
        compose_word_state(emphasized, 0, "all") as all_active,
    ):
        same(original, all_active)
    effective = emphasized["cues"][0]["layers"][0]["font_info"]["effective"]
    assert effective["font_face"] == 1 and effective["effective_axes"] == {"wght": 600}
    # A deliberately uncovered primary forces the existing whole-body fallback.
    primary = tmp_path / "madina-missing.ttf"
    with TTFont(asset_path("fonts", "quran_font.ttf")) as face:
        for table in face["cmap"].tables:
            table.cmap.pop(ord("خ"), None)
        face.save(primary)
    data["assets"] = {"arabic": font_selector(primary)}
    data["profile"]["styles"]["arabic"] = {
        "decoration_layout": "elements",
        "font_fallbacks": [font_selector(FONTS / "ScheherazadeNew-Regular.ttf")],
    }
    result = checked(data)
    assert result["cues"][0]["layers"][0]["font_info"]["fallback_used"]


def test_memory_and_disk_cache_revalidate_pins_and_variant_checksums(tmp_path):
    data = request(tmp_path, layout="elements")
    data["assets"] = {"arabic": font_selector(FONTS / "ScheherazadeNew-Regular.ttf")}
    data["word_emphasis"] = {}
    data["cues"][0]["word_states"] = [{"state_id": "none", "default_weight": 0}]
    data["asset_cache_directory"] = str(tmp_path / "cache")
    cache = CaptionRenderCache()
    a, b = checked(data, cache=cache), checked(data, cache=cache)
    assert a["assets"] == b["assets"]
    variant_id = a["cues"][0]["word_emphasis"]["states"][0]["asset_ids"][0]
    (tmp_path / "cache" / (variant_id + ".png")).write_bytes(b"corrupt")
    result = execute_request(data, cache=cache).to_dict()
    assert result["cues"][0]["error"]["code"] == "corrupt_asset_cache"
    assert result["cues"][0]["word_emphasis"]["states"][0]["asset_ids"] == []
    data["assets"]["arabic"]["sha256"] = "0" * 64
    result = execute_request(data, cache=cache).to_dict()
    assert result["cues"][0]["error"]["code"] == "changed_asset"


def test_probe_limits_and_cancellation_publish_nothing(tmp_path, monkeypatch):
    import quran_image_generator.word_masks as masks

    data = request(tmp_path)
    data["word_emphasis"] = {}
    monkeypatch.setattr(masks, "MAX_PROBES", 2)
    assert execute_request(data).payload["cues"][0]["error"]["code"] == "resource_limit"
    monkeypatch.setattr(masks, "MAX_PROBES", 4096)
    count = 0

    def cancel():
        nonlocal count
        count += 1
        return count > 5

    result = execute_request(data, cancelled=cancel).to_dict()
    assert result["error"]["code"] == "cancelled" and result["assets"] == []
    assert not (tmp_path / "output with spaces").exists()
    monkeypatch.setattr(masks, "MAX_MASK_BYTES", 100)
    assert execute_request(data).payload["cues"][0]["error"]["code"] == "resource_limit"


def test_public_transition_endpoints_linear_channels_and_alpha_not_doubled():
    with (
        Image.new("RGBA", (2, 1), (20, 40, 60, 85)) as a,
        Image.new("RGBA", (2, 1), (100, 120, 140, 85)) as b,
    ):
        with (
            interpolate_word_states(a, b, 0) as zero,
            interpolate_word_states(a, b, 1) as one,
            interpolate_word_states(a, b, 0.5) as middle,
        ):
            same(zero, a)
            same(one, b)
            assert middle.getpixel((0, 0)) == (60, 80, 100, 85)
        for progress in (-1, 2, float("nan"), True):
            with pytest.raises(ReferenceError):
                interpolate_word_states(a, b, progress)
    with (
        Image.new("RGBA", (1, 1), (255, 0, 0, 0)) as a,
        Image.new("RGBA", (1, 1), (0, 255, 0, 100)) as b,
        interpolate_word_states(a, b, 0.5) as half,
    ):
        assert half.getpixel((0, 0)) == (0, 255, 0, 50)


@pytest.mark.parametrize("layout", ["legacy", "elements"])
def test_long_partial_mixed_basmala_forced_preferred_and_shrink_layout_is_shared(
    tmp_path, layout
):
    spans = [
        asdict(SourceSpan(0, 0, 1, 4)),
        asdict(SourceSpan(2, 255, 1, 18)),
        asdict(SourceSpan(31, 9, 6, 8)),
    ]
    data = request(
        tmp_path,
        spans=spans,
        layout=layout,
        style={
            "font_size": 48,
            "min_font_size": 15,
            "fit": "shrink",
            "region": [0.25, 0.2, 0.75, 0.85],
        },
    )
    data["cues"][0]["line_breaks"] = [
        {"span_occurrence": 1, "source_word": 4, "mode": "preferred"},
        {"span_occurrence": 1, "source_word": 9, "mode": "forced"},
    ]
    baseline = checked(data)
    data["word_emphasis"] = {}
    data["cues"][0]["word_states"] = [
        {"state_id": "all"},
        {"state_id": "dim", "default_weight": 0},
    ]
    result = checked(data)
    arabic = next(
        plan
        for plan in result["cues"][0]["layers"]
        if plan["layer"]["role"] == "arabic"
    )
    assert len(arabic["lines"]) > 2 and arabic["font_size"] < 48
    assert arabic == baseline["cues"][0]["layers"][0]
    assert (
        arabic["typography"]["forced_breaks"]
        and arabic["typography"]["preferred_breaks"]
    )
    assert (
        len(
            [
                m
                for unit in result["cues"][0]["word_emphasis"]["units"]
                for m in unit["members"]
            ]
        )
        == 25
    )
    with (
        compose_caption(baseline, 0, (576, 1024)) as before,
        compose_word_state(result, 0, "all") as after,
    ):
        same(before, after)


def test_legacy_mixed_marker_font_and_elements_ornaments_remain_static(tmp_path):
    for layout in ("legacy", "elements"):
        data = request(
            tmp_path,
            spans=[asdict(SourceSpan(31, 9, 6, 8))] * 2,
            layout=layout,
            style={
                "numeral_system": "latin",
                "quote_open": "(",
                "quote_close": ")",
                "marker_prefix": "[",
                "marker_suffix": "]",
                "quotation_style": {"color": "#00CCFF"},
                "marker_style": {"color": "#FFD700"},
            },
        )
        selector = font_selector(asset_path("fonts", "multilingual_fonts", "am.ttf"))
        data["assets"] = (
            {"decorations": selector}
            if layout == "legacy"
            else {"quotes": selector, "markers": selector}
        )
        baseline = checked(data)
        data["word_emphasis"] = {"active_color": "#FFFFFF", "inactive_color": "#FFFFFF"}
        data["cues"][0]["word_states"] = [{"state_id": "same", "default_weight": 0.3}]
        result = checked(data)
        with (
            compose_caption(baseline, 0, (576, 1024)) as before,
            compose_word_state(result, 0, "same") as after,
        ):
            same(before, after)
        if layout == "elements":
            data["word_emphasis"] = {}
            data["cues"][0]["word_states"] = [
                {"state_id": "all"},
                {"state_id": "none", "default_weight": 0},
            ]
            result = checked(data)
            with (
                compose_word_state(result, 0, "all") as all_active,
                compose_word_state(result, 0, "none") as none,
            ):
                for rgb in ((0, 204, 255), (255, 215, 0)):
                    pixels = list(rgba_pixels(all_active))
                    assert any(p[:3] == rgb and p[3] for p in pixels)
                    assert bytes(p[3] if p[:3] == rgb else 0 for p in pixels) == bytes(
                        p[3] if p[:3] == rgb else 0 for p in rgba_pixels(none)
                    )


def test_legacy_inline_quote_shared_pixels_are_protected_and_reported(tmp_path):
    data = request(tmp_path, spans=[asdict(SourceSpan(1, 1, 1, 4))])
    data["word_emphasis"] = {}
    result = checked(data)
    assert (
        sum(
            p["protected_decoration_pixels"]
            for unit in result["cues"][0]["word_emphasis"]["units"]
            for p in unit["parts"]
        )
        > 0
    )


def test_public_example_uses_one_layout_and_writes_verified_states_and_fade(tmp_path):
    namespace = runpy.run_path(
        str(Path(__file__).parent.parent / "examples" / "word_emphasis.py")
    )
    data = request(tmp_path, layout="elements")
    result = namespace["example"](data, tmp_path / "example", 0, 1, 0.5)
    assert result["status"] == "complete"
    for name in ("all", "inactive", "current", "cumulative", "transition"):
        with Image.open(tmp_path / "example" / (name + ".png")) as image:
            assert image.mode == "RGBA" and image.size == (576, 1024)


@pytest.mark.parametrize(
    "field,value", [("default_weight", float("nan")), ("default_weight", 1.1)]
)
def test_weights_are_finite_and_bounded(tmp_path, field, value):
    data = request(tmp_path)
    data["word_emphasis"] = {}
    data["cues"][0]["word_states"] = [{"state_id": "bad", field: value}]
    assert execute_request(data).payload["error"]["code"] == "invalid_request"


def test_state_and_source_group_limits(tmp_path):
    data = request(
        tmp_path, operation="layout", style={"font_size": 10, "min_font_size": 8}
    )
    data["word_emphasis"] = {}
    data["cues"][0]["word_states"] = [{"state_id": str(i)} for i in range(33)]
    assert execute_request(data).payload["error"]["code"] == "invalid_request"
    data["cues"][0].pop("word_states")
    data["cues"][0]["spans"] = [
        asdict(SourceSpan(2, 282, 1, 129)),
        asdict(SourceSpan(31, 9, 1, 5)),
    ]
    assert execute_request(data).payload["cues"][0]["error"]["code"] == "resource_limit"


def test_partial_failed_state_never_leaves_published_asset_references(tmp_path):
    data = request(tmp_path)
    data.update(word_emphasis={}, error_mode="per_cue")
    data["cues"].append(
        {
            "cue_id": "bad",
            "spans": [asdict(SourceSpan(31, 9, 1, 5))],
            "word_states": [
                {
                    "state_id": "bad",
                    "words": [{"span_occurrence": 3, "source_word": 1, "weight": 1}],
                }
            ],
        }
    )
    result = execute_request(data).to_dict()
    assert result["status"] == "partial" and result["cues"][1]["asset_ids"] == []
    assert result["cues"][0]["word_emphasis"]["states"][0]["asset_ids"]


def test_joint_fit_common_size_revalidation_and_cropped_state_reconstruction(tmp_path):
    data = group_request(tmp_path)
    data["caption_groups"][0].update(region=[0.2, 0.4, 0.8, 0.62], gap=0.3)
    baseline = checked(data)
    suggestion = common_size_suggestion(baseline)
    data["profile"] = {
        "id": "plain",
        "revision": "1",
        "approval": "approved",
        "provenance": {},
        "styles": {
            role: {"font_size": size}
            for role, size in suggestion["reference_sizes"].items()
        },
    }
    revalidated = checked(data)
    data["word_emphasis"] = {
        "mode": "both",
        "background": {"padding": [0, 0], "corner_radius": 0},
    }
    data["cues"][0]["word_states"] = [
        {
            "state_id": "one",
            "default_weight": 0,
            "words": [{"span_occurrence": 0, "source_word": 2, "weight": 0.6}],
        }
    ]
    full = checked(data)
    data["cropped"] = True
    cropped = checked(data)
    assert full["cues"][0]["layers"] == revalidated["cues"][0]["layers"]
    assert (
        cropped["cues"][0]["word_emphasis"]["layout_id"]
        == full["cues"][0]["word_emphasis"]["layout_id"]
    )
    with (
        compose_word_state(full, 0, "one") as a,
        compose_word_state(cropped, 0, "one") as b,
    ):
        same(a, b)


def test_hidden_arabic_and_reserved_font_feature_report_useful_errors(tmp_path):
    from fontTools.ttLib.tables import otTables as ot

    data = request(tmp_path, operation="layout", style={"enabled": False})
    data["word_emphasis"] = {}
    assert (
        execute_request(data).payload["cues"][0]["error"]["code"]
        == "unsupported_word_emphasis_option"
    )
    collision = tmp_path / "reserved.ttf"
    with TTFont(FONTS / "ScheherazadeNew-Regular.ttf") as font:
        record = ot.FeatureRecord()
        record.FeatureTag, record.Feature = "QIGW", ot.Feature()
        (
            record.Feature.FeatureParams,
            record.Feature.LookupListIndex,
            record.Feature.LookupCount,
        ) = None, [], 0
        font["GPOS"].table.FeatureList.FeatureRecord.append(record)
        font["GPOS"].table.FeatureList.FeatureCount += 1
        font.save(collision)
    data["profile"]["styles"]["arabic"].pop("enabled")
    data["assets"] = {"arabic": font_selector(collision)}
    result = execute_request(data).to_dict()
    assert result["cues"][0]["error"]["code"] == "unsupported_word_emphasis_font"
    assert result["cues"][0]["error"]["details"]["feature"] == "QIGW"


def test_ligature_crossing_source_word_boundary_is_atomic_even_with_disjoint_masks(
    tmp_path,
):
    text = select_excerpt(ExcerptRequest("cluster", (SourceSpan(1, 1, 1, 4),))).text
    first, second, *_ = text.split()
    path = tmp_path / "cross-word.ttf"
    with TTFont(FONTS / "ScheherazadeNew-Regular.ttf") as font:
        del font["GSUB"]
        cmap = font.getBestCmap()
        names = " ".join(sorted({cmap[ord(ch)] for ch in text if not ch.isspace()}))
        noop = f"sub [{names}] by [{names}];"
        # Keep nominal forms in this purpose-built fixture and replace the
        # first word's tail, separator, and second word's initial with one glyph.
        features = "".join(
            f"feature {tag} {{ {noop} }} {tag};"
            for tag in ("init", "medi", "fina", "isol")
        )
        cluster = first[-2:] + " " + second[0]
        components = " ".join(cmap[ord(ch)] for ch in cluster)
        features += (
            f"feature rlig {{ sub {components} by {cmap[ord(first[-2])]}; }} rlig;"
        )
        addOpenTypeFeaturesFromString(font, features, tables=["GSUB"])
        font.save(path)
    face = ImageFont.truetype(str(path), 30, layout_engine=ImageFont.Layout.RAQM)
    assert face.getlength(text, direction="rtl") < face.getlength(
        text, direction="rtl", features=["-rlig"]
    )
    data = request(tmp_path, spans=[asdict(SourceSpan(1, 1, 1, 4))], layout="elements")
    data["assets"] = {"arabic": font_selector(path)}
    baseline = checked(data)
    data["word_emphasis"] = {}
    result = checked(data)
    group = result["cues"][0]["word_emphasis"]["units"][0]
    assert group["atomic"] and "shaping_cluster" in group["atomic_reasons"]
    assert [member["source_word"] for member in group["members"]] == [1, 2]
    evidence = next(e for e in group["atomic_evidence"] if e["kind"] == "consumed_source_initial")
    assert evidence["reason"] == "shaping_cluster"
    assert len(evidence["run_character_ranges"]) == 2
    assert evidence["nominal_outline"] and not evidence["cursive_disabled_initial_visible"]
    a, b = evidence["consumed_initial_range"]
    assert evidence["run_text"][b - 1] == second[0] and a < b
    assert evidence["prepared_font_sha256"] and evidence["mask_font_sha256"]
    with (
        compose_caption(baseline, 0, (576, 1024)) as before,
        compose_word_state(result, 0, "all") as after,
    ):
        same(before, after)
    data["cues"][0]["word_states"] = [
        {
            "state_id": "split",
            "default_weight": 0,
            "words": [{"span_occurrence": 0, "source_word": 2, "weight": 1}],
        }
    ]
    assert (
        execute_request(data).payload["cues"][0]["error"]["code"] == "atomic_word_split"
    )
