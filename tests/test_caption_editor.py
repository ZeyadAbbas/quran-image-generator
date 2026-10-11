import copy
import hashlib
import json
from dataclasses import asdict

import pytest
from PIL import Image

from quran_image_generator.api import execute_request
from quran_image_generator.bindings import TranslationSource
from quran_image_generator.caption_editor import (
    STYLE_FIELDS,
    CaptionDocument,
    compose_caption,
    parse_style_value,
)
from quran_image_generator.references import ReferenceError, SourceSpan
from quran_image_generator.resources import asset_path
from quran_image_generator.snapshots import SnapshotStore


def test_document_roundtrip_preserves_repeats_metadata_and_paths(tmp_path):
    document = CaptionDocument(root=tmp_path)
    document.data["metadata"] = {"consumer": "any app", "nested": {"x": 1}}
    document.data["cues"][0]["metadata"] = {"start_seconds": 1.2, "end_seconds": 3}
    document.set_style("arabic", {"font_size": 27.25, "horizontal_scale": 1.2})
    logo = tmp_path / "custom logo.png"
    Image.new("RGBA", (32, 16), "red").save(logo)
    document.set_asset("logo", logo.name, "test terms", "Test creator")
    index = document.duplicate_cue(0)
    assert index == 1
    assert document.data["cues"][0]["spans"] == document.data["cues"][1]["spans"]
    assert document.data["cues"][0]["cue_id"] != document.data["cues"][1]["cue_id"]
    path = tmp_path / "portable request.json"
    document.save(path)
    loaded = CaptionDocument.load(path)
    assert loaded.request().to_dict() == document.request().to_dict()
    assert loaded.data["assets"]["logo"]["path"] == str(logo)


def test_style_validation_does_not_replace_previous_styles(tmp_path):
    document = CaptionDocument(root=tmp_path)
    document.set_style("translation", {"font_size": 21.75})
    before = copy.deepcopy(document.profile())
    with pytest.raises(ReferenceError):
        document.set_style("translation", {"unknown_field": 10})
    assert document.profile() == before


@pytest.mark.parametrize(
    "name,value",
    [
        ("font_size", "nan"),
        ("opacity", "inf"),
        ("anchor", "1"),
        ("z_order", "2.3"),
        ("enabled", "false"),
    ],
)
def test_native_field_parse_rejects_invalid_types(name, value):
    with pytest.raises(ReferenceError, match="Invalid"):
        parse_style_value(name, value)


def test_source_ranges_validated_before_mutation(tmp_path):
    document = CaptionDocument(root=tmp_path)
    before = copy.deepcopy(document.data)
    with pytest.raises(ReferenceError):
        document.add_span(0, SourceSpan(1, 1, 1, 1000))
    assert document.data == before
    document.add_span(0, SourceSpan(0, 0, 1, 4))
    assert document.spans(0)[-1].surah == 0
    assert document.word_count(0, 0) == 4


def test_binding_hashes_review_and_immutable_snapshot(tmp_path):
    document = CaptionDocument(root=tmp_path)
    source = TranslationSource(
        "local", "authored test", "1", "Test author", "test", "Fixture"
    )
    document.bind(
        0,
        source,
        binding_id="test-phrase",
        revision="1",
        source_text="Test source phrase.",
        segments=("Test source phrase.",),
        approved=True,
        reviewer="Test reviewer",
        edited=False,
    )
    dataset = document.dataset()
    assert dataset is not None
    binding = dataset.bindings[0]
    assert binding.source_identity_sha256 == source.identity_sha256
    assert (
        binding.arabic_sha256 == hashlib.sha256(document.arabic(0).encode()).hexdigest()
    )
    pin = SnapshotStore(tmp_path / "snapshots").import_dataset(dataset)
    document.pin_snapshot(tmp_path / "snapshots", pin)
    before = copy.deepcopy(document.data)
    with pytest.raises(ReferenceError, match="local copy"):
        document.bind(
            0,
            source,
            binding_id="test-phrase",
            revision="2",
            source_text="Test source phrase.",
            segments=("Edited phrase.",),
            approved=True,
            reviewer="Test reviewer",
            edited=True,
        )
    assert document.data == before
    document.set_dataset(document.dataset())
    document.bind(
        0,
        source,
        binding_id="test-phrase",
        revision="2",
        source_text="Test source phrase.",
        segments=("Edited phrase.",),
        approved=False,
        reviewer="",
        edited=True,
    )
    assert document.dataset().bindings[0].review_status == "needs_review"
    assert SnapshotStore(tmp_path / "snapshots").bindings(pin) == dataset


def test_composed_cropped_assets_equal_full_canvas_and_detect_tampering(tmp_path):
    document = CaptionDocument(root=tmp_path)
    document.data["titles"] = True
    document.data["cues"][0]["arabic_title"] = "الفاتحة"
    document.set_asset(
        "arabic", str(asset_path("fonts", "quran_font.ttf")), "bundled", "Test"
    )
    document.profile()["approval"] = "approved"
    cropped = {**document.request().to_dict(), "cropped": True}
    full = execute_request(document.request()).to_dict()
    crop = execute_request(cropped).to_dict()
    assert full["status"] == crop["status"] == "complete"
    size = (576, 1024)
    image = compose_caption(full, 0, size)
    assert image.tobytes() == compose_caption(crop, 0, size).tobytes()
    assert image.getpixel((0, 0))[3] == 0
    asset = crop["assets"][0]
    from pathlib import Path

    path = Path(crop["job_directory"]) / asset["path"]
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(ReferenceError, match="changed"):
        compose_caption(crop, 0, size)


def test_default_editor_is_generic_and_all_styles_are_published(tmp_path):
    document = CaptionDocument(root=tmp_path)
    assert "quranscribe" not in json.dumps(document.request().to_dict()).lower()
    assert set(document.styles("arabic")) == set(STYLE_FIELDS)
    assert document.data["cues"][0]["spans"] == [asdict(SourceSpan(1, 1, 1, 4))]
