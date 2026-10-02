import copy
import hashlib
import json
from pathlib import Path

import pytest
import requests
from PIL import Image, ImageDraw

from quran_image_generator.api import execute_request, runtime_identity
from quran_image_generator.references import SourceSpan, resolve_span
from scripts.caption_review import assert_image_matches, composite_cue, image_difference

ROOT = Path(__file__).parent / "fixtures" / "captions"
FIXTURES = json.loads((ROOT / "six-references.json").read_text("utf-8"))


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=lambda c: c["clip_id"])
def test_six_reference_content_alpha_bounds_and_repeats(case, tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Deterministic renderer attempted external HTTP")

    monkeypatch.setattr(requests.Session, "request", no_network)
    request = {
        **case["request"],
        "translation_dataset": FIXTURES["translation_dataset"],
        "output_directory": str(tmp_path),
        "cropped": True,
    }
    result = execute_request(request).to_dict()
    assert result["status"] == "needs_review", result
    records = {asset["asset_id"]: asset for asset in result["assets"]}
    identities = {}
    for cue, expected in zip(result["cues"], case["expected"], strict=True):
        plans = {plan["layer"]["role"]: plan for plan in cue["layers"]}
        assert cue["arabic"] == expected["arabic"]
        assert (
            hashlib.sha256(cue["arabic"].encode()).hexdigest()
            == expected["arabic_sha256"]
        )
        assert cue["source_spans"][0]["starts_ayah"] == expected["starts_ayah"]
        assert cue["source_spans"][0]["ends_ayah"] == expected["ends_ayah"]
        assert cue["status"] == "needs_review"
        assert cue["translation"]["binding"]["review_status"] == "approved"
        assert (
            plans["arabic"]["layer"]["suffix"] != ""
            if expected["ends_ayah"]
            else plans["arabic"]["layer"]["suffix"] == ""
        )
        assert {records[key]["roles"][0] for key in cue["asset_ids"]} == {
            "arabic",
            "translation",
            "arabic_title",
            "latin_title",
        }
        identity = (cue["arabic"], cue["translation"]["binding"]["binding_id"])
        if identity in identities:
            assert identities[identity] == cue["asset_ids"]
        identities[identity] = cue["asset_ids"]
        assert plans["arabic"]["lines"][-1][2] == 512
        assert plans["translation"]["lines"][0][2] == 0.56 * 1024
    for asset in records.values():
        path = Path(result["job_directory"]) / asset["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]
        with Image.open(path) as image:
            assert image.mode == "RGBA"
            assert image.size == (asset["width"], asset["height"])
            alpha = image.getchannel("A")
            bounds = alpha.getbbox()
            x, y = asset["offset"]
            assert (
                list((bounds[0] + x, bounds[1] + y, bounds[2] + x, bounds[3] + y))
                == asset["bounds"]
            )
            assert any(0 < value < 255 for value in alpha.getdata())
            allowed = asset["effect_bounds"]
            assert asset["bounds"][0] >= allowed[0] and asset["bounds"][1] >= allowed[1]
            assert asset["bounds"][2] <= allowed[2] and asset["bounds"][3] <= allowed[3]
    composite = composite_cue(result, result["cues"][0], (576, 1024))
    assert composite.getpixel((0, 0))[3] == 0
    golden = ROOT / "goldens" / f"{case['clip_id']}.png"
    with Image.open(golden) as reference:
        # Cross-runtime structural checks are distinct from pixel approval.
        difference = image_difference(reference, composite)
        assert difference["bounds_drift"] <= 16, difference
        old_ink = sum(reference.getchannel("A").getdata())
        new_ink = sum(composite.getchannel("A").getdata())
        assert 0.7 <= new_ink / old_ink <= 1.3
        pinned = json.loads((ROOT / "goldens" / "runtime.json").read_text("utf-8"))
        if pinned["runtime"] == runtime_identity():
            assert_image_matches(reference, composite)


def test_visual_diff_rejects_shift_clipping_and_opaque_background():
    with Image.open(ROOT / "goldens" / "7339743928691821854.png") as reference:
        assert_image_matches(reference, reference.copy())
        shifted = Image.new("RGBA", reference.size)
        shifted.alpha_composite(reference, (14, 0))
        with pytest.raises(AssertionError):
            assert_image_matches(reference, shifted)
        clipped = reference.copy()
        bounds = reference.getchannel("A").getbbox()
        ImageDraw.Draw(clipped).rectangle(
            (0, bounds[1], reference.width, bounds[1] + 20), fill=(0, 0, 0, 0)
        )
        with pytest.raises(AssertionError):
            assert_image_matches(reference, clipped)
        opaque = Image.new("RGBA", reference.size, "black")
        opaque.alpha_composite(reference)
        with pytest.raises(AssertionError):
            assert_image_matches(reference, opaque)


def test_pixel_similarity_cannot_substitute_for_reference_identity(tmp_path):
    request = copy.deepcopy(FIXTURES["cases"][0]["request"])
    request.update(
        operation="layout", translation_dataset=FIXTURES["translation_dataset"]
    )
    request["cues"][0]["spans"][0]["word_end"] = 4
    result = execute_request(request).to_dict()
    assert result["cues"][0]["error"]["code"] == "stale_translation"
    assert result["assets"] == []


def test_authored_17_13_spelling_equivalences_and_terminal_words():
    assert resolve_span(SourceSpan(17, 13, 7, 11)).text == "وَنُخْرِجُ لَهُۥ يَوْمَ ٱلْقِيَٰمَةِ كِتَٰبًا"
    assert resolve_span(SourceSpan(39, 30, 4, 4)).text == "مَّيِّتُونَ"
    assert resolve_span(SourceSpan(5, 73, 25, 25)).text == "أَلِيمٌ"


@pytest.mark.parametrize("size", [(576, 1024), (1080, 1920), (360, 800), (1280, 720)])
def test_reference_profile_dimensions_and_persistent_anchors(size):
    request = copy.deepcopy(FIXTURES["cases"][0]["request"])
    request.update(
        operation="layout", translation_dataset=FIXTURES["translation_dataset"]
    )
    request["cues"] = request["cues"][:2]
    request["canvas"] = dict(zip(("width", "height"), size, strict=True))
    if size[0] > size[1]:
        request["profile"]["styles"]["arabic"]["region"] = [0.05, 0.22, 0.95, 0.65]
        request["profile"]["styles"]["arabic_title"].update(
            anchor=[0.5, 0.12], region=[0.05, 0.01, 0.95, 0.22]
        )
        request["profile"]["styles"]["latin_title"].update(
            anchor=[0.5, 0.3], region=[0.05, 0.23, 0.95, 0.38]
        )
        request["profile"]["styles"]["translation"].update(
            anchor=[0.5, 0.75], region=[0.05, 0.62, 0.95, 0.92]
        )
    result = execute_request(request).to_dict()
    assert result["status"] == "needs_review", result
    assert [
        plan["bounds"]
        for plan in result["cues"][0]["layers"]
        if plan["layer"]["persistent"]
    ] == [
        plan["bounds"]
        for plan in result["cues"][1]["layers"]
        if plan["layer"]["persistent"]
    ]
