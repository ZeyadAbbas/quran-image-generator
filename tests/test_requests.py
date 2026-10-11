"""Consumer requests exercise the same scene capabilities through Python and JSON."""

import json
import os
import subprocess
import sys
from dataclasses import replace

import pytest
from test_bindings import fixture_dataset

from quran_image_generator.api import capabilities, execute_request
from quran_image_generator.profiles import (
    CaptionProfile,
    export_profile,
    import_profile,
)
from quran_image_generator.references import ReferenceError
from quran_image_generator.requests import AssetSelector, BatchRequest, CueRequest
from quran_image_generator.resources import asset_path
from quran_image_generator.scenes import checked_asset


def test_full_typed_request_matches_json_and_does_not_change_defaults(tmp_path):
    dataset = fixture_dataset()
    font = str(asset_path("fonts", "multilingual_fonts", "am.ttf"))
    selector = AssetSelector(font, checked_asset(font), "test-only", "Bundled fixture")
    profile = CaptionProfile(
        "consumer-style",
        "7",
        "approved",
        {
            "arabic": {
                "font_size": 29.25,
                "horizontal_scale": 1.05,
                "quote_open": "(",
                "quote_close": ")",
                "numeral_system": "latin",
                "marker_prefix": "(",
                "marker_suffix": ")",
                "suffix_offset": -4,
                "outline_width": 0.5,
                "shadow_offset": (0, 1),
                "shadow_blur": 1,
                "shadow_opacity": 0.3,
            },
            "logo": {"font_size": 45.5, "color": "#FFFFFF"},
        },
        {"author": "Explicit consumer request"},
    )
    path = tmp_path / "consumer profile.json"
    export_profile(profile, path)
    profile = import_profile(path)
    binding = dataset.bindings[0]
    cue = CueRequest(
        "first",
        binding.spans,
        "required",
        binding.binding_id,
        {"start_seconds": 1, "end_seconds": 3},
        arabic_title="سورة لقمان",
        latin_title="Surah Luqman",
    )
    batch = BatchRequest(
        "consumer",
        (cue, replace(cue, cue_id="repeat")),
        operation="render_batch",
        output_directory=str(tmp_path / "jobs"),
        profile=profile,
        titles=True,
        quotations=True,
        verse_numbers=True,
        cropped=True,
        assets={"decorations": selector, "logo": replace(selector, glyph="Q")},
        translation_dataset=dataset,
        asset_cache_directory=str(tmp_path / "cache"),
        deadline_seconds=120,
        require_approved_profile=True,
    )
    request = batch.to_request()
    python = execute_request(request).to_dict()
    assert python["status"] == "complete", python
    assert python["cues"][0]["asset_ids"] == python["cues"][1]["asset_ids"]
    assert {a["roles"][0] for a in python["assets"]} == {
        "arabic",
        "translation",
        "arabic_title",
        "latin_title",
        "logo",
    }
    arabic = next(
        p for p in python["cues"][0]["layers"] if p["layer"]["role"] == "arabic"
    )
    assert arabic["font_size"] == 29.25 and arabic["ornament_positions"]
    assert arabic["decoration_asset_sha256"] == selector.sha256
    plan = tmp_path / "caption request.json"
    plan.write_text(json.dumps(request.to_dict(), ensure_ascii=False), "utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(
            __import__("pathlib").Path(__file__).resolve().parents[1] / "src"
        ),
    }
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "quran_image_generator.machine_cli",
            "--request",
            str(plan),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    machine = json.loads(process.stdout)
    assert machine["assets"] == python["assets"] and machine["cues"] == python["cues"]
    plain = execute_request(
        BatchRequest(
            "plain",
            (replace(cue, translation_policy="none", translation_binding_id=None),),
        ).to_request()
    ).to_dict()
    assert plain["status"] == "complete" and plain["profile"]["id"] == "plain"
    assert {p["layer"]["role"] for p in plain["cues"][0]["layers"]} == {"arabic"}
    assert [
        p["layer"]["role"] for p in plain["cues"][0]["layers"] if p["status"] == "ready"
    ] == ["arabic"]


@pytest.mark.parametrize(
    "styles", [{"typo": {"font_size": 24}}, {"arabic": {"typo": 1}}]
)
def test_profile_import_and_typed_calls_reject_silent_style_omissions(tmp_path, styles):
    profile = CaptionProfile("caller", "1", "approved", styles, {"author": "caller"})
    with pytest.raises(ReferenceError) as error:
        profile.validate()
    assert error.value.code == "invalid_profile"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(__import__("dataclasses").asdict(profile)), "utf-8")
    with pytest.raises(ReferenceError):
        import_profile(path)


def test_capabilities_advertise_generic_features_without_consumer_presets():
    info = capabilities()
    assert info["profiles"] == [
        {"id": "plain", "revision": "1", "approval": "approved"}
    ]
    assert info["custom_profiles"] and info["features"]["separate_decoration_font"]
    assert (
        "horizontal_scale" in info["style_fields"]
        and "font" not in info["style_fields"]
    )
