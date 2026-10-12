import copy
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from PIL import Image
from test_api import fixture_request
from test_bindings import fixture_dataset

from quran_image_generator.api import execute_request
from quran_image_generator.bindings import BindingDataset, text_hash
from quran_image_generator.caption_editor import CaptionDocument, compose_caption
from quran_image_generator.excerpts import ExcerptRequest, select_excerpt
from quran_image_generator.references import CorpusIdentity, SourceSpan
from quran_image_generator.requests import (
    Annotation,
    BatchRequest,
    CueRequest,
    TrackBindingRef,
    TranslationTrack,
)
from quran_image_generator.resources import asset_path
from quran_image_generator.scenes import checked_asset
from quran_image_generator.snapshots import SnapshotStore


def edition(resource="fixture-english", text=None, direction="ltr", spans=None):
    base = fixture_dataset()
    source = replace(base.source, resource=resource, direction=direction)
    binding = replace(base.bindings[0], source_identity_sha256=source.identity_sha256)
    if text is not None:
        binding = replace(binding, source_text=text, source_text_sha256=text_hash(text), segments=(text,))
    if spans is not None:
        binding = replace(binding, spans=spans, arabic_sha256=text_hash(select_excerpt(ExcerptRequest("fixture", spans)).text))
    return replace(base, source=source, bindings=(binding,))


def font(name="am.ttf"):
    path = asset_path("fonts", "quran_font.ttf") if name == "quran_font.ttf" else asset_path("fonts", "multilingual_fonts", name)
    return {"path": str(path), "sha256": checked_asset(str(path)), "license": "Bundled test font; see notices", "attribution": "Bundled font fixture"}


def track_request(tmp_path, operation="render_batch"):
    data = fixture_request(tmp_path, operation)
    data["translation_tracks"] = [
        {"track_id": "translation-en", "language": "en", "dataset": edition().to_dict(), "binding": {"binding_id": "31-9-prefix", "revision": "1"},
         "font": font(), "style": {"color": "#00FF00", "panel": {"opacity": 0.25}}},
        {"track_id": "translation-ur", "language": "ur", "dataset": edition("fixture-urdu", "عبارت", "rtl").to_dict(), "binding": {"binding_id": "31-9-prefix", "revision": "1"},
         "font": font("quran_font.ttf"), "style": {"color": "#FFAA00", "font_size": 22, "panel": {"opacity": 0.25}}},
    ]
    data["annotations"] = [{"annotation_id": "source-label", "kind": "source_reference", "format": "compact", "style": {"color": "#00FFFF"}}]
    data["caption_groups"] = [{"group_id": "caption", "mode": "flow", "layers": ["arabic", "translation-en", "translation-ur", "source-label"],
                               "region": [0.05, 0.1, 0.95, 0.9], "fit": "shrink", "gap": 0.6}]
    return data


def test_multilingual_pixels_have_correct_ids_terms_styles_and_repeat_dedup(tmp_path):
    data = track_request(tmp_path)
    result = execute_request(data).to_dict()
    assert result["status"] == "complete", result
    cue = result["cues"][0]
    layers = {p["layer"]["instance_id"]: p for p in cue["layers"]}
    assert layers["translation-en"]["layer"]["direction"] == "ltr"
    assert layers["translation-ur"]["layer"]["direction"] == "rtl"
    assert layers["translation-en"]["layer"]["font"] != layers["translation-ur"]["layer"]["font"]
    assert result["cues"][0]["asset_ids"] == result["cues"][1]["asset_ids"]
    assert len(result["assets"]) == 4
    for track in cue["translation_tracks"]:
        plan = layers[track["track_id"]]
        asset = next(a for a in result["assets"] if a["asset_id"] == plan["asset_id"])
        assert asset["instance_ids"] == [track["track_id"]]
        path = Path(result["job_directory"]) / asset["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]
        assert track["binding"]["review_status"] == "approved"
        assert plan["font_info"]["inputs"][0]["license"] == track["font"]["license"]
        with Image.open(path) as png:
            target = (0, 255, 0) if track["track_id"] == "translation-en" else (255, 170, 0)
            assert any(pixel[:3] == target and pixel[3] for _, pixel in png.convert("RGBA").getcolors(png.width * png.height))


def test_disabled_and_missing_optional_tracks_reclaim_slots_without_approval_edits(tmp_path):
    data = track_request(tmp_path, "layout")
    original = execute_request(data).to_dict()
    data["translation_tracks"][1].update(enabled=False, snapshot={"directory": "missing", "sha256": "0" * 64})
    data["translation_tracks"][1].pop("dataset")
    data["translation_tracks"][0].update(translation_policy="review")
    data["translation_tracks"][0].pop("binding")
    result = execute_request(data).to_dict()
    assert result["status"] == "needs_review", result
    cue = result["cues"][0]
    assert [p["status"] for p in cue["layers"] if p["layer"]["role"] == "translation"] == ["omitted_optional", "disabled"]
    assert cue["translation_tracks"][1]["status"] == "disabled"
    assert cue["translation_tracks"][0]["binding"] is None
    arabic = next(p for p in cue["layers"] if p["layer"]["role"] == "arabic")
    label = next(p for p in cue["layers"] if p["layer"]["role"] == "source_reference")
    assert label["bounds"][1] - arabic["bounds"][3] == pytest.approx(18, abs=1)
    assert label["layout_info"]["group_bounds"][3] - label["layout_info"]["group_bounds"][1] < original["cues"][0]["layers"][0]["layout_info"]["group_bounds"][3] - original["cues"][0]["layers"][0]["layout_info"]["group_bounds"][1]


def test_reorder_and_independent_style_leave_other_binding_unchanged(tmp_path):
    data = track_request(tmp_path, "inspect")
    original = execute_request(data).to_dict()
    data["translation_tracks"][0]["style"]["color"] = "#8800FF"
    data["caption_groups"][0]["layers"][1:3] = ["translation-ur", "translation-en"]
    result = execute_request(data).to_dict()
    assert result["status"] == "complete", result
    assert result["cues"][0]["translation_tracks"] == original["cues"][0]["translation_tracks"]
    layers = {p["layer"]["instance_id"]: p for p in result["cues"][0]["layers"]}
    assert layers["translation-ur"]["bounds"][3] < layers["translation-en"]["bounds"][1]
    assert layers["translation-ur"]["layer"]["color"] == "#FFAA00"
    inspections = {p["instance_id"]: p for p in result["cues"][0]["inspection"]["layers"]}
    assert inspections["translation-en"]["origins"]["color"] == "explicit"


def test_same_text_two_editions_retain_distinct_review_and_identity(tmp_path):
    data = track_request(tmp_path)
    second = copy.deepcopy(data["translation_tracks"][0])
    second.update(track_id="translation-en-second", dataset=edition("different-edition").to_dict())
    data["translation_tracks"][1] = second
    data["caption_groups"][0]["layers"][2] = second["track_id"]
    result = execute_request(data).to_dict()
    assert result["status"] == "complete", result
    records = result["cues"][0]["translation_tracks"]
    assert records[0]["binding"]["segments"] == records[1]["binding"]["segments"]
    assert records[0]["binding"]["source_identity_sha256"] != records[1]["binding"]["source_identity_sha256"]
    assert len({p["asset_id"] for p in result["cues"][0]["layers"] if p["layer"]["role"] == "translation"}) == 2


@pytest.mark.parametrize("change,code,suffix", [
    ({"binding": {"binding_id": "31-9-prefix", "revision": "stale"}}, "stale_translation", "/binding/revision"),
    ({"binding": {"binding_id": "missing", "revision": "1"}}, "missing_translation", "/binding"),
    ({"dataset": None}, "missing_translation", "/binding"),
])
def test_required_failures_are_track_specific_and_publish_nothing(tmp_path, change, code, suffix):
    data = track_request(tmp_path)
    data["translation_tracks"][1].update(change)
    if data["translation_tracks"][1].get("dataset") is None:
        data["translation_tracks"][1].pop("dataset")
    result = execute_request(data).to_dict()
    assert result["status"] == "failed" and result["assets"] == [], result
    assert len(result["cues"]) == 2
    for cue in result["cues"]:
        error = cue["error"]
        assert error["code"] == code
        assert error["details"]["track_id"] == "translation-ur"
        assert error["details"]["path"] == "/translation_tracks/1" + suffix
    assert not Path(data["output_directory"]).exists()


def test_per_cue_binding_revision_failures_and_legacy_dataset_can_coexist(tmp_path):
    data = track_request(tmp_path)
    data["translation_dataset"] = fixture_dataset().to_dict()
    for cue in data["cues"]:
        cue.update(translation_policy="required", translation_binding_id="31-9-prefix")
    data["caption_groups"][0]["layers"].insert(1, "translation")
    data["cues"][1]["track_bindings"] = {"translation-ur": {"binding_id": "31-9-prefix", "revision": "stale"}}
    data["error_mode"] = "per_cue"
    result = execute_request(data).to_dict()
    assert result["status"] == "partial", result
    assert result["cues"][0]["translation"]["binding"]["review_status"] == "approved"
    assert result["cues"][1]["error"]["details"]["path"] == "/cues/1/track_bindings/translation-ur/revision"
    assert result["assets"] and not result["cues"][1]["asset_ids"]


def test_draft_requires_explicit_consent_and_never_looks_approved(tmp_path):
    data = track_request(tmp_path, "layout")
    draft = data["translation_tracks"][0]
    draft["dataset"]["bindings"][0]["review_status"] = "needs_review"
    denied = execute_request(data).to_dict()
    assert denied["cues"][0]["error"]["code"] == "translation_review"
    draft["translation_policy"] = "review"
    hidden = execute_request(data).to_dict()
    assert hidden["status"] == "needs_review"
    assert hidden["cues"][0]["translation_tracks"][0]["displayed"] is False
    draft["preview_unreviewed_translation"] = True
    shown = execute_request(data).to_dict()
    assert shown["status"] == "needs_review"
    assert shown["cues"][0]["translation_tracks"][0]["displayed"] is True
    assert shown["cues"][0]["translation_tracks"][0]["binding"]["review_status"] == "needs_review"


def test_partial_repeated_multichapter_labels_and_basmala_never_invent_endings(tmp_path):
    data = fixture_request(tmp_path, "layout")
    spans = [asdict(SourceSpan(1, 1, 1, 2)), asdict(SourceSpan(2, 1, 1, 1)), asdict(SourceSpan(1, 1, 1, 2)), asdict(SourceSpan(0, 0, 1, 4))]
    data["cues"] = [{"cue_id": "mixed", "spans": spans}]
    data["annotations"] = [{"annotation_id": "source-label", "kind": "source_reference", "format": "compact"}]
    data["caption_groups"] = [{"group_id": "caption", "mode": "flow", "layers": ["arabic", "source-label"], "fit": "shrink"}]
    data["verse_numbers"] = True
    data["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "styles": {"arabic": {"decoration_layout": "elements"}}, "provenance": {}}
    result = execute_request(data).to_dict()
    assert result["status"] == "complete", result
    label = result["cues"][0]["annotations"][0]["text"]
    assert label == "1:1 (words 1-2); 2:1; 1:1 (words 1-2); Basmala (words 1-4)"
    arabic = next(p for p in result["cues"][0]["layers"] if p["layer"]["role"] == "arabic")
    assert len(arabic["layer"]["marker_specs"]) == 1
    assert arabic["layer"]["marker_specs"][0]["surah"] == 2


def test_edition_and_approved_text_labels_are_distinct_from_quran(tmp_path):
    data = track_request(tmp_path, "layout")
    data["annotations"].extend([
        {"annotation_id": "edition-en", "kind": "edition_label", "track_id": "translation-en"},
        {"annotation_id": "note", "kind": "annotation", "text": "Approved presentation label", "approved": True},
    ])
    data["caption_groups"][0]["layers"].extend(["edition-en", "note"])
    result = execute_request(data).to_dict()
    assert result["status"] == "complete", result
    assert "fixture-english (1)" in result["cues"][0]["annotations"][1]["text"]
    expected = select_excerpt(ExcerptRequest("expected", (SourceSpan(31, 9, 1, 5),))).text
    assert result["cues"][0]["arabic"] == expected
    data["annotations"][0]["text"] = "Caller cannot replace source"
    assert execute_request(data).to_dict()["error"]["code"] == "invalid_annotation"
    data["annotations"][0].pop("text")
    data["annotations"][2]["approved"] = False
    assert execute_request(data).to_dict()["error"]["code"] == "annotation_review"


def test_layout_is_required_and_cross_group_collisions_are_rejected(tmp_path):
    data = track_request(tmp_path, "layout")
    data.pop("caption_groups")
    result = execute_request(data).to_dict()
    assert result["cues"][0]["error"]["code"] == "missing_group_layout"
    data["caption_groups"] = [{"group_id": "each-" + identity, "layers": [identity], "collision": "reject"}
                              for identity in ("translation-en", "translation-ur", "source-label")]
    result = execute_request(data).to_dict()
    assert result["cues"][0]["error"]["code"] == "layer_collision"


def test_impossible_group_fit_identifies_instance_and_keeps_all_or_nothing(tmp_path):
    data = track_request(tmp_path)
    data["caption_groups"][0]["region"] = [0.49, 0.49, 0.51, 0.51]
    result = execute_request(data).to_dict()
    assert result["cues"][0]["error"]["code"] == "group_fit_failed"
    assert result["assets"] == [] and not Path(data["output_directory"]).exists()


def test_offline_snapshot_crop_and_caption_studio_roundtrip_match_pixels(tmp_path):
    data = track_request(tmp_path)
    directory = tmp_path / "snapshots"
    for track in data["translation_tracks"]:
        digest = SnapshotStore(directory).import_dataset(BindingDataset.from_dict(track.pop("dataset")))
        track["snapshot"] = {"directory": str(directory), "sha256": digest}
    document = CaptionDocument(data, root=tmp_path)
    document.set_caption_instances(data["translation_tracks"], data["annotations"], {}, 0)
    path = tmp_path / "tracks.json"
    document.save(path)
    opened = CaptionDocument.load(path)
    full = execute_request(opened.request()).to_dict()
    data["cropped"] = True
    cropped = execute_request(data).to_dict()
    assert full["status"] == cropped["status"] == "complete", (full, cropped)
    with compose_caption(full, 0, (576, 1024)) as a, compose_caption(cropped, 0, (576, 1024)) as b:
        assert a.tobytes() == b.tobytes()
    repeated = execute_request(opened.request()).to_dict()
    assert [a["sha256"] for a in repeated["assets"]] == [a["sha256"] for a in full["assets"]]
    for record in full["cues"][0]["translation_tracks"]:
        assert record["snapshot"]["sha256"] and record["font"]["license"]


def test_typed_python_and_json_contract_match(tmp_path):
    batch = BatchRequest("typed-tracks", (CueRequest("cue", (SourceSpan(31, 9, 1, 5),)),),
                         translation_tracks=(TranslationTrack("english", dataset=edition(), binding=TrackBindingRef("31-9-prefix", "1")),),
                         annotations=(Annotation("ref"),), caption_groups=({"group_id": "caption", "mode": "flow", "layers": ["arabic", "english", "ref"], "fit": "shrink"},))
    data = batch.to_request().to_dict()
    expected = execute_request(data).to_dict()
    assert expected["status"] == "complete", expected
    path = tmp_path / "request.json"
    path.write_text(json.dumps(data), "utf-8")
    command = subprocess.run([sys.executable, "-m", "quran_image_generator.machine_cli", "--request", str(path)], capture_output=True, text=True, encoding="utf-8")
    assert command.returncode == 0 and command.stderr == ""
    assert json.loads(command.stdout) == expected


@pytest.mark.parametrize("mutation", ["duplicate", "reserved", "unknown-binding", "missing-revision", "mixed-dataset", "body", "too-many"])
def test_bounded_strict_instance_contract(tmp_path, mutation):
    data = track_request(tmp_path, "layout")
    if mutation == "duplicate":
        data["translation_tracks"][1]["track_id"] = "translation-en"
    elif mutation == "reserved":
        data["translation_tracks"][0]["track_id"] = "arabic"
    elif mutation == "unknown-binding":
        data["cues"][0]["track_bindings"] = {"unknown": {"binding_id": "x", "revision": "1"}}
    elif mutation == "missing-revision":
        data["translation_tracks"][0]["binding"].pop("revision")
    elif mutation == "mixed-dataset":
        data["translation_tracks"][0]["snapshot"] = {"directory": "x", "sha256": "0" * 64}
    elif mutation == "body":
        data["translation_tracks"][0]["text"] = "Unreviewed text"
    else:
        data["translation_tracks"] *= 5
    result = execute_request(data).to_dict()
    assert result["status"] == "failed" and result["error"]["details"]["path"].startswith(("/translation_tracks", "/cues")), result


def test_changed_source_font_pin_and_cancellation_report_exact_track(tmp_path):
    data = track_request(tmp_path, "layout")
    data["translation_tracks"][1]["font"]["sha256"] = "0" * 64
    result = execute_request(data).to_dict()
    assert result["cues"][0]["error"]["details"]["track_id"] == "translation-ur"
    data = track_request(tmp_path, "layout")
    data["translation_tracks"][1]["dataset"]["bindings"][0]["source_identity_sha256"] = "0" * 64
    result = execute_request(data).to_dict()
    assert result["cues"][0]["error"]["details"]["path"] == "/translation_tracks/1/dataset"
    cancelled = execute_request(track_request(tmp_path), cancelled=lambda: True).to_dict()
    assert cancelled["error"]["code"] == "cancelled" and not cancelled["assets"]


def test_shared_quran_selection_runs_once_per_uncached_cue(monkeypatch, tmp_path):
    import quran_image_generator.api as api

    original = api.select_excerpt
    calls = []

    def observed(request):
        calls.append(request)
        return original(request)

    monkeypatch.setattr(api, "select_excerpt", observed)
    data = track_request(tmp_path, "layout")
    result = execute_request(data).to_dict()
    assert result["status"] == "complete", result
    assert len(calls) == 1
    assert result["corpus"]["source"] == asdict(CorpusIdentity())


@pytest.mark.parametrize("field,value", [("color", "bad-color"), ("region", [0.9, 0.1, 0.1, 0.9]), ("font_size", 5)])
def test_instance_style_errors_point_to_own_style(tmp_path, field, value):
    data = track_request(tmp_path, "layout")
    data["translation_tracks"][1]["style"][field] = value
    result = execute_request(data).to_dict()
    error = result["cues"][0]["error"]
    assert error["details"]["track_id"] == "translation-ur"
    assert error["details"]["path"] == f"/translation_tracks/1/style/{field}"


def test_direction_and_fit_obligation_cannot_be_silently_overridden(tmp_path):
    data = track_request(tmp_path, "layout")
    data["translation_tracks"][1]["style"]["direction"] = "ltr"
    result = execute_request(data).to_dict()
    assert result["cues"][0]["error"]["details"]["path"] == "/translation_tracks/1/style/direction"
    data["translation_tracks"][1]["style"].pop("direction")
    data["translation_tracks"][1]["style"]["required"] = False
    result = execute_request(data).to_dict()
    assert result["status"] == "complete", result
    data["translation_tracks"][1].pop("binding")
    result = execute_request(data).to_dict()
    assert result["cues"][0]["error"]["code"] == "missing_translation"


def test_pinned_snapshot_corruption_and_real_urdu_coverage_fail_explicitly(tmp_path):
    data = track_request(tmp_path, "layout")
    track = data["translation_tracks"][1]
    store = SnapshotStore(tmp_path / "snapshots")
    digest = store.import_dataset(BindingDataset.from_dict(track.pop("dataset")))
    track["snapshot"] = {"directory": str(store.directory), "sha256": digest}
    (store.directory / f"{digest}.json").write_text("{}", "utf-8")
    result = execute_request(data).to_dict()
    assert result["cues"][0]["error"]["code"] == "corrupt_snapshot"
    assert result["cues"][0]["error"]["details"]["path"] == "/translation_tracks/1/snapshot"
    data = track_request(tmp_path, "layout")
    data["translation_tracks"][1]["dataset"] = edition("fixture-urdu", "یہ ایک آزمائشی عبارت ہے", "rtl").to_dict()
    result = execute_request(data).to_dict()
    error = result["cues"][0]["error"]
    assert error["code"] == "missing_glyph" and error["details"]["track_id"] == "translation-ur"
    assert "U+06CC" in error["details"]["candidates"][0]["coverage"]["missing_codepoints"]


def test_installed_copyable_example_preflight_and_generic_legacy_styles_are_isolated(tmp_path):
    example = Path(__file__).resolve().parents[1] / "examples" / "captions" / "translation-tracks.json"
    data = json.loads(example.read_text("utf-8"))
    data.update(operation="preflight", output_directory=str(tmp_path))
    data["profile"] = {"id": "plain", "revision": "1", "approval": "approved", "styles": {"translation": {"color": "#FF0000"}}, "provenance": {}}
    result = execute_request(data).to_dict()
    assert result["status"] == "complete" and result["preflight"]["ready"], result
    assert not result["assets"]
    assert [p["layer"]["color"] for p in result["cues"][0]["layers"] if p["layer"]["role"] == "translation"] == ["#FFFFFF", "#FFD166"]
