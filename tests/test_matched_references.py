"""Per-layer reference gates and optional caller-font rendering without redistribution."""

import hashlib
import json
import os

import pytest
from PIL import Image

from scripts.reference_handoff import BASELINE, assert_layer_matches, verify_handoff


@pytest.fixture(scope="module")
def golden_layers():
    data = json.loads((BASELINE / "baseline.json").read_text("utf-8"))
    assert data["approval"] == "needs_review" and len(data["cases"]) == 6
    assert data["caption_layouts"] == 64 and data["python_json_parity"]
    layers = {}
    for case in data["cases"]:
        assert {layer["role"] for layer in case["layers"]} == {
            "arabic",
            "translation",
            "arabic_title",
            "latin_title",
            "logo",
        }
        for record in case["layers"]:
            path = BASELINE / record["path"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
            canvas = Image.new("RGBA", (576, 1024))
            with Image.open(path) as crop:
                assert crop.mode == "RGBA"
                assert crop.size == (
                    record["bounds"][2] - record["bounds"][0],
                    record["bounds"][3] - record["bounds"][1],
                )
                canvas.alpha_composite(crop, tuple(record["bounds"][:2]))
            assert list(canvas.getchannel("A").getbbox()) == record["bounds"]
            layers[case["clip_id"], record["role"]] = canvas
    return layers


@pytest.mark.parametrize(
    "role", ["arabic", "translation", "arabic_title", "latin_title", "logo"]
)
def test_each_matched_layer_gate_rejects_missing_shifted_and_wrong_color(
    role, golden_layers
):
    reference = golden_layers["7339743928691821854", role]
    assert_layer_matches(reference, reference.copy(), pixel=True)
    with pytest.raises(AssertionError):
        assert_layer_matches(reference, Image.new("RGBA", reference.size), pixel=True)
    shifted = Image.new("RGBA", reference.size)
    shifted.alpha_composite(reference, (12, 0))
    with pytest.raises(AssertionError):
        assert_layer_matches(reference, shifted, pixel=True)
    colored = Image.new("RGBA", reference.size, (255, 0, 0, 0))
    colored.putalpha(reference.getchannel("A"))
    with pytest.raises(AssertionError):
        assert_layer_matches(reference, colored, pixel=True)


def test_all_matched_layers_are_independently_checked(golden_layers):
    assert len(golden_layers) == 30


@pytest.mark.skipif(
    not os.environ.get("QIG_REFERENCE_FONT_DIRECTORY")
    or not os.environ.get("QIG_REFERENCE_LATIN_FONT"),
    reason="Original fonts are caller-supplied; set both explicit reference-font paths",
)
def test_real_matched_requests_fit_and_reproduce_layers(tmp_path):
    from pathlib import Path

    report = verify_handoff(
        Path(os.environ["QIG_REFERENCE_FONT_DIRECTORY"]),
        Path(os.environ["QIG_REFERENCE_LATIN_FONT"]),
        tmp_path,
        machine=False,
    )
    assert report["status"] == "passed" and report["caption_layouts"] == 64
