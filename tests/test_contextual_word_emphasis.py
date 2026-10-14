"""Native DigitalKhatt regressions for decoration and false atomic boundaries."""

import pytest
from contextual_helpers import signature_request, static_assets, with_static_layers
from test_word_emphasis import assert_changes_inside, checked, same

from quran_image_generator.caption_editor import compose_caption
from quran_image_generator.references import SourceSpan
from quran_image_generator.word_emphasis import (
    compose_word_state,
    interpolate_word_states,
)

EXCERPTS = [
    SourceSpan(35, 1, 11, 13),  # #94: formerly mistaken for a decoration join.
    SourceSpan(35, 1, 1, 10),
    SourceSpan(35, 1, 19, 24),
    SourceSpan(35, 4, 1, 7),
    SourceSpan(35, 2, 10, 11),
    SourceSpan(35, 5, 12, 13),
]


@pytest.mark.parametrize("span", EXCERPTS)
@pytest.mark.parametrize("ornaments", [False, True])
def test_actual_madina_words_are_separate_and_original_raster_is_unchanged(
    tmp_path, span, ornaments
):
    data = signature_request(tmp_path, span, ornaments=ornaments, spacing=0.2)
    baseline = checked(data)
    data["word_emphasis"] = {}
    data["cues"][0]["word_states"] = [
        {"state_id": "all"},
        {"state_id": "none", "default_weight": 0},
        {
            "state_id": "second",
            "default_weight": 0,
            "words": [
                {"span_occurrence": 0, "source_word": span.word_start + 1, "weight": 1}
            ],
        },
    ]
    result = checked(data)
    cue = result["cues"][0]
    units = cue["word_emphasis"]["units"]
    assert [u["members"][0]["source_word"] for u in units] == list(
        range(span.word_start, span.word_end + 1)
    )
    assert all(len(u["members"]) == 1 and not u["atomic"] for u in units)
    assert cue["layers"] == baseline["cues"][0]["layers"]
    assert cue["arabic"] == baseline["cues"][0]["arabic"]
    effective = cue["layers"][0]["font_info"]["effective"]
    assert effective["sha256"] == data["assets"]["arabic"]["sha256"]
    with (
        compose_caption(baseline, 0, (576, 1024)) as static,
        compose_word_state(result, 0, "all") as all_active,
        compose_word_state(result, 0, "none") as none,
        compose_word_state(result, 0, "second") as second,
    ):
        same(static, all_active)
        same(static.getchannel("A"), second.getchannel("A"))
        assert_changes_inside(none, second, [units[1]])
        # This also proves independently positioned quotation/verse pixels stay fixed.
        assert_changes_inside(all_active, none, units)


@pytest.mark.parametrize(
    "span,starts,time",
    [
        (EXCERPTS[1], [0.292, 1.032], 0.5),
        (EXCERPTS[2], [18, 19.492, 20.252, 20.852], 19.8),
        (EXCERPTS[3], [67.292, 68.092, 69.532, 70.212, 71.232, 72.852, 73.892], 67.5),
    ],
)
@pytest.mark.parametrize("fade", [0, 0.12])
def test_distinct_audio_starts_can_select_current_read_and_fades_without_early_words(
    tmp_path, span, starts, time, fade
):
    data = signature_request(tmp_path, span, spacing=0.2)
    # Repeated exact source occurrences and a forced line boundary retain selectors.
    data["cues"][0]["spans"] *= 2
    data["cues"][0]["line_breaks"] = [
        {"span_occurrence": 1, "source_word": span.word_start, "mode": "forced"}
    ]
    if span == EXCERPTS[1]:
        data["cues"][0]["line_breaks"].append(
            {"span_occurrence": 0, "source_word": 6, "mode": "forced"}
        )
    data["word_emphasis"] = {"active_color": "#00FF00", "inactive_color": "#A6A6A6"}
    active = max(i for i, start in enumerate(starts) if start <= time)
    if fade:
        time = starts[active] + fade * 0.5
    read = [
        {
            "span_occurrence": 1,
            "source_word": span.word_start + i,
            "weight": min(1, (time - start) / fade) if fade else 1,
        }
        for i, start in enumerate(starts)
        if start <= time
    ]
    data["cues"][0]["word_states"] = [
        {"state_id": "none", "default_weight": 0},
        {"state_id": "read", "default_weight": 0, "words": read},
        {"state_id": "current", "default_weight": 0, "words": [read[active]]},
    ]
    result = checked(data)
    units = result["cues"][0]["word_emphasis"]["units"]
    states = {s["state_id"]: s for s in result["cues"][0]["word_emphasis"]["states"]}
    assert len({p["line_index"] for u in units for p in u["parts"]}) > 1
    for i, unit in enumerate(units):
        assert len(unit["members"]) == 1
        member = unit["members"][0]
        word_index = member["source_word"] - span.word_start
        if member["span_occurrence"] == 0 or word_index > active:
            assert (
                states["read"]["weights"][i]["weight"]
                == states["current"]["weights"][i]["weight"]
                == 0
            )
    current_units = [
        u for i, u in enumerate(units) if states["current"]["weights"][i]["weight"]
    ]
    assert len(current_units) == 1
    if fade:
        assert next(
            w["weight"] for w in states["current"]["weights"] if w["weight"]
        ) == pytest.approx(0.5)
    with (
        compose_word_state(result, 0, "none") as none,
        compose_word_state(result, 0, "current") as current,
        compose_word_state(result, 0, "read") as read_image,
    ):
        assert_changes_inside(none, current, current_units)
        for progress in (0, 0.4, 1):
            with interpolate_word_states(current, read_image, progress) as frame:
                same(current.getchannel("A"), frame.getchannel("A"))
                if progress == 0:
                    same(current, frame)
                if progress == 1:
                    same(read_image, frame)


def test_signature_zero_spacing_static_layers_and_real_repaint(tmp_path):
    span = EXCERPTS[0]
    data = signature_request(tmp_path, span)
    with_static_layers(data, [span])
    baseline = checked(data)
    data["word_emphasis"] = {"active_color": "#FFFFFF", "inactive_color": "#FFFFFF"}
    data["cues"][0]["word_states"] = [{"state_id": "repaint", "default_weight": 0.4}]
    result = checked(data)
    cue = result["cues"][0]
    assert len(cue["word_emphasis"]["units"]) == 3
    assert static_assets(cue) == static_assets(baseline["cues"][0])
    assert cue["translation"] == baseline["cues"][0]["translation"]
    assert cue["translation_tracks"] == baseline["cues"][0]["translation_tracks"]
    assert set(static_assets(cue)).issubset(
        cue["word_emphasis"]["states"][0]["asset_ids"]
    )
    with (
        compose_caption(baseline, 0, (576, 1024)) as static,
        compose_word_state(result, 0, "repaint") as repaint,
    ):
        same(static, repaint)


def test_madina_fractional_scaled_variable_font_keeps_exact_geometry(tmp_path):
    data = signature_request(tmp_path, EXCERPTS[2], spacing=0.2)
    data["profile"]["styles"]["arabic"].update(
        font_size=31.5,
        horizontal_scale=1.07,
        opacity=0.73,
    )
    baseline = checked(data)
    data["word_emphasis"] = {"active_color": "#FFFFFF", "inactive_color": "#FFFFFF"}
    data["cues"][0]["word_states"] = [{"state_id": "repaint", "default_weight": 0.5}]
    result = checked(data)
    assert result["cues"][0]["layers"] == baseline["cues"][0]["layers"]
    with (
        compose_caption(baseline, 0, (576, 1024)) as original,
        compose_word_state(result, 0, "repaint") as repaint,
    ):
        same(original, repaint)


def test_out_of_bounds_pair_in_issue_95_stays_an_explicit_reference_error(tmp_path):
    from quran_image_generator.api import execute_request

    data = signature_request(tmp_path, SourceSpan(35, 3, 26, 27))
    data["word_emphasis"] = {}
    result = execute_request(data).payload
    assert result["cues"][0]["error"]["code"] == "invalid_reference"
    assert result["assets"] == []


def test_true_decoration_ligature_is_still_rejected_with_actual_run_evidence(tmp_path):
    from dataclasses import asdict

    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
    from fontTools.ttLib import TTFont
    from test_font_controls import font_selector
    from test_word_emphasis import FONTS, request

    from quran_image_generator.api import execute_request
    from quran_image_generator.excerpts import ExcerptRequest, select_excerpt

    span = SourceSpan(1, 1, 1, 4)
    text = select_excerpt(ExcerptRequest("fixture", (span,))).text
    # An Arabic ornament stays in the same RTL shaping run as the source.
    # Common-script brackets can instead form a separate RAQM item.
    data = request(tmp_path, spans=[asdict(span)], style={"quote_open": "ل"})
    baseline = checked(data)
    quote = baseline["cues"][0]["layers"][0]["layer"]["quote_open"]
    path = tmp_path / "true-decoration-ligature.ttf"
    with TTFont(FONTS / "ScheherazadeNew-Regular.ttf") as font:
        del font["GSUB"]
        cmap = font.getBestCmap()
        names = " ".join(sorted({cmap[ord(ch)] for ch in text if not ch.isspace()}))
        noop = f"sub [{names}] by [{names}];"
        features = "".join(
            f"feature {tag} {{ {noop} }} {tag};"
            for tag in ("init", "medi", "fina", "isol")
        )
        components = " ".join(cmap[ord(ch)] for ch in quote[-1] + " " + text[0])
        features += (
            f"feature rlig {{ sub {components} by {cmap[ord(quote[-1])]}; }} rlig;"
        )
        addOpenTypeFeaturesFromString(font, features, tables=["GSUB"])
        font.save(path)
    data["assets"] = {"arabic": font_selector(path)}
    checked(data)  # Ordinary static output remains allowed.
    data["word_emphasis"] = {}
    result = execute_request(data).payload
    error = result["cues"][0]["error"]
    assert error["code"] == "word_decoration_atomic" and result["assets"] == []
    details = error["details"]
    assert details["static_character_ranges"] and details["run_character_ranges"]
    assert details["prepared_font_sha256"] and details["mask_font_sha256"]
    assert details["members"][0]["source_word"] == 1
