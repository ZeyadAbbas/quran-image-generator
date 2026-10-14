"""The explicitly selected Simple edition has exact verified source ownership."""

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict

import jsonschema
import pytest
from contextual_helpers import static_assets, with_static_layers
from test_content import CATALOG, FakeResponse, QueueSession, _chapter_one_translation
from test_translation_api import source_request
from test_word_emphasis import assert_changes_inside, checked, request, same

from quran_image_generator import references
from quran_image_generator.api import capabilities, execute_request, style_descriptor
from quran_image_generator.bindings import BindingDataset
from quran_image_generator.caption_editor import CaptionDocument, compose_caption
from quran_image_generator.content import QuranDataClient
from quran_image_generator.contract_schema import REQUEST_SCHEMA
from quran_image_generator.references import (
    SIMPLE_DISPLAY_REVISION,
    SIMPLE_SHA256,
    ReferenceError,
    SourceSpan,
    bridge_data,
    resolve_span,
    simple_corpus,
    simple_word_groups,
)
from quran_image_generator.requests import BatchRequest, CueRequest
from quran_image_generator.resources import asset_path
from quran_image_generator.snapshots import SnapshotStore, prepare_quranenc_snapshot
from quran_image_generator.word_emphasis import compose_word_state

SPAN = SourceSpan(2, 267, 1, 1)


def simple_request(tmp_path, *, spans=None, operation="render_batch"):
    data = request(
        tmp_path, spans=spans or [asdict(SPAN)], layout="elements", operation=operation
    )
    data["arabic_script"] = "simple"
    return data


def test_exact_boundary_simple_text_and_capability_corpus_identity(tmp_path):
    with pytest.raises(ReferenceError) as error:
        resolve_span(SPAN)
    assert error.value.code == "mapping_boundary"
    span = resolve_span(SPAN, arabic_script="simple")
    assert span.text == "يَا"
    assert span.source == SPAN and span.character_start == 0 and span.character_end == 3
    assert (
        span.mapping_revision == SIMPLE_DISPLAY_REVISION
        and span.target_sha256 == SIMPLE_SHA256
    )
    assert span.starts_ayah and not span.ends_ayah
    data = simple_request(tmp_path, operation="layout")
    data["word_emphasis"] = {}
    result = checked(data)
    assert result["cues"][0]["arabic"] == span.text
    assert result["corpus"]["display_script"] == "simple"
    assert result["corpus"]["target_sha256"] == SIMPLE_SHA256
    assert result["corpus"]["mapping_revision"] == SIMPLE_DISPLAY_REVISION
    assert result["cues"][0]["word_emphasis"]["units"][0]["members"] == [
        {
            "cue_id": "words",
            "span_occurrence": 0,
            "surah": 2,
            "ayah": 267,
            "source_word": 1,
        }
    ]
    rendering = capabilities()["source_rendering"]
    assert rendering == style_descriptor()["source_rendering"]
    assert rendering["default"] == "uthmani" and not rendering["automatic_fallback"]
    assert rendering["scripts"]["simple"]["sha256"] == SIMPLE_SHA256
    assert rendering["scripts"]["simple"]["verified_verbatim"]
    data.pop("arabic_script")
    assert (
        execute_request(data).payload["cues"][0]["error"]["code"] == "mapping_boundary"
    )


def test_all_simple_ayah_ranges_match_canonical_index_and_verbatim_bytes():
    raw = asset_path("data", "quran-simple-1.1.txt").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SIMPLE_SHA256
    assert len(simple_corpus()) == 6236
    for key, record in bridge_data()["verses"].items():
        surah, ayah = map(int, key.split(":"))
        span = SourceSpan(surah, ayah, 1, record["word_count"])
        text, groups = simple_word_groups(span)
        assert len(groups) == record["word_count"]
        resolved = resolve_span(span, arabic_script="simple")
        assert resolved.text == text[groups[0][2] : groups[-1][3]]
        assert resolved.starts_ayah and resolved.ends_ayah
    assert (
        resolve_span(SourceSpan(0, 0, 1, 4), arabic_script="simple").text
        == simple_corpus()["1:1"]
    )
    # Ayah 2:1 excludes its separate download basmala exactly; caller 0:0 addresses it.
    assert resolve_span(SourceSpan(2, 1, 1, 1), arabic_script="simple").text == "الم"
    with pytest.raises(TypeError):
        simple_corpus()["2:267"] = "replacement"


def test_simple_corrupt_asset_unsupported_identity_and_no_replacement_text(
    tmp_path, monkeypatch
):
    original = references._package_bytes
    simple_corpus.cache_clear()
    monkeypatch.setattr(
        references,
        "_package_bytes",
        lambda path: (
            b"bad" if path.endswith("quran-simple-1.1.txt") else original(path)
        ),
    )
    data = simple_request(tmp_path, operation="layout")
    try:
        assert (
            execute_request(data).payload["cues"][0]["error"]["code"]
            == "corrupt_corpus"
        )
    finally:
        simple_corpus.cache_clear()
    monkeypatch.setattr(references, "_package_bytes", original)
    for change in (
        {"arabic_script": "caller"},
        {"arabic_text": "يَا"},
        {"arabic_offsets": [0, 3]},
    ):
        assert (
            execute_request({**data, **change}).payload["error"]["code"]
            == "invalid_request"
        )
    data["source_corpus"]["sha256"] = "0" * 64
    assert execute_request(data).payload["error"]["code"] == "unsupported_corpus"
    with pytest.raises(ReferenceError) as error:
        resolve_span(SourceSpan(35, 3, 26, 27), arabic_script="simple")
    assert error.value.code == "invalid_reference"


@pytest.mark.parametrize("cropped", [False, True])
@pytest.mark.parametrize("mode", ["fill", "background", "both"])
def test_simple_repeated_occurrences_states_geometry_and_static_assets(
    tmp_path, cropped, mode
):
    spans = [SPAN, SPAN]
    data = simple_request(tmp_path, spans=[asdict(s) for s in spans])
    data["cropped"] = cropped
    data["profile"]["styles"]["arabic"].update(
        shadow_blur=1, shadow_opacity=0.3, outline_width=0.5
    )
    with_static_layers(data, spans, script="simple")
    data["cues"][0]["line_breaks"] = [
        {"span_occurrence": 0, "source_word": 1, "mode": "forced"}
    ]
    baseline = checked(data)
    data["word_emphasis"] = {"mode": mode}
    data["cues"][0]["word_states"] = [
        {"state_id": "none", "default_weight": 0},
        {
            "state_id": "second",
            "default_weight": 0,
            "words": [{"span_occurrence": 1, "source_word": 1, "weight": 1}],
        },
    ]
    result = checked(data)
    cue = result["cues"][0]
    units = cue["word_emphasis"]["units"]
    assert len(units) == 2 and not any(u["atomic"] for u in units)
    assert [u["members"][0]["span_occurrence"] for u in units] == [0, 1]
    assert cue["layers"] == baseline["cues"][0]["layers"]
    assert static_assets(cue) == static_assets(baseline["cues"][0])
    assert cue["translation"] == baseline["cues"][0]["translation"]
    for state in cue["word_emphasis"]["states"]:
        assert set(static_assets(cue)).issubset(state["asset_ids"])
    with (
        compose_word_state(result, 0, "none") as none,
        compose_word_state(result, 0, "second") as second,
    ):
        if mode == "fill":
            assert_changes_inside(none, second, [units[1]])
        else:
            assert none.tobytes() != second.tobytes()
    data["word_emphasis"] = {}
    data["cues"][0]["word_states"] = [{"state_id": "all"}]
    neutral = checked(data)
    with (
        compose_caption(baseline, 0, (576, 1024)) as original,
        compose_word_state(neutral, 0, "all") as all_active,
    ):
        same(original, all_active)
    assert (
        neutral["cues"][0]["word_emphasis"]["layout_id"]
        == cue["word_emphasis"]["layout_id"]
    )


def test_simple_bindings_snapshots_reject_mismatched_display_hash(tmp_path):
    span = SourceSpan(31, 9, 1, 5)
    data = simple_request(tmp_path, spans=[asdict(span)], operation="layout")
    dataset = with_static_layers(data, [span], script="simple")
    dataset.validate()
    assert BindingDataset.from_dict(dataset.to_dict()) == dataset
    store = SnapshotStore(tmp_path / "snapshots")
    # Use public import/export and the snapshot format, without altering binding identities.
    from quran_image_generator.bindings import export_bindings, import_bindings

    path = tmp_path / "binding.json"
    export_bindings(dataset, path)
    assert import_bindings(path) == dataset
    pin = store.import_dataset(dataset)
    assert store.bindings(pin) == dataset
    original = checked(data)
    data.pop("translation_dataset")
    data["translation_snapshot"] = {"directory": str(store.directory), "sha256": pin}
    assert checked(data)["cues"][0]["translation"] == original["cues"][0]["translation"]
    from test_bindings import fixture_dataset

    data.pop("translation_snapshot")
    data["translation_dataset"] = fixture_dataset().to_dict()
    failure = execute_request(data).payload["cues"][0]["error"]
    assert failure["code"] == "stale_translation" and failure["details"][
        "path"
    ].endswith("/translation_binding_id")
    data.pop("translation_dataset")
    data["cues"][0]["translation_policy"] = "none"
    data["translation_tracks"][0]["dataset"] = fixture_dataset().to_dict()
    assert (
        execute_request(data).payload["cues"][0]["error"]["code"] == "stale_translation"
    )


def test_simple_translation_preparation_drafts_full_ayah_and_never_expands_partial(
    tmp_path, monkeypatch
):
    client = QuranDataClient(
        session=QueueSession(
            FakeResponse(CATALOG),
            FakeResponse(_chapter_one_translation()),
            FakeResponse(CATALOG),
        )
    )
    monkeypatch.setattr(
        "quran_image_generator.translation_api.prepare_quranenc_snapshot",
        lambda store, key, chapters, **kw: prepare_quranenc_snapshot(
            store, key, chapters, client=client, **kw
        ),
    )
    data = source_request(tmp_path)
    data["arabic_script"] = "simple"
    result = checked(data)["translation_preparation"]
    assert [c["status"] for c in result["cues"]] == [
        "bound",
        "bound",
        "needs_phrase_review",
    ]
    assert result["cues"][2]["binding_id"] is None
    assert (
        result["dataset"]["bindings"][0]["mapping_revision"] == SIMPLE_DISPLAY_REVISION
    )
    BindingDataset.from_dict(result["dataset"]).validate()


def test_simple_typed_cli_editor_preflight_roundtrip_and_script_layout_identity(
    tmp_path,
):
    batch = BatchRequest(
        "typed-simple",
        (CueRequest("c", (SPAN,)),),
        arabic_script="simple",
        word_emphasis={},
        output_directory=str(tmp_path / "output"),
    )
    data = batch.to_request().to_dict()
    assert checked(data)["cues"][0]["arabic"] == "يَا"
    jsonschema.validate(data, REQUEST_SCHEMA)
    path = tmp_path / "request.json"
    CaptionDocument(data).save(path)
    assert CaptionDocument.load(path).request("layout").to_dict() == data
    path.write_text(json.dumps(data), encoding="utf8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "quran_image_generator.machine_cli",
            "--request",
            str(path),
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(asset_path().parent.parent)},
        capture_output=True,
        encoding="utf8",
    )
    assert result.returncode == 0 and result.stderr == ""
    assert json.loads(result.stdout)["cues"][0]["arabic"] == "يَا"
    data["operation"] = "preflight"
    preflight = checked(data)
    assert (
        preflight["preflight"]["checks"]["source_rendering"]["sha256"] == SIMPLE_SHA256
    )
    # Same drawn text still has a distinct source identity in immutable layouts.
    layouts = []
    for script in ("simple", "uthmani"):
        same_text = simple_request(
            tmp_path, spans=[asdict(SourceSpan(1, 1, 1, 4))], operation="layout"
        )
        same_text["arabic_script"] = script
        same_text["word_emphasis"] = {}
        layouts.append(checked(same_text)["cues"][0]["word_emphasis"]["layout_id"])
    assert layouts[0] != layouts[1]
