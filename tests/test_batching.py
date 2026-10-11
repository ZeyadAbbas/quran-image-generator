from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

from test_api import fixture_request

from quran_image_generator import api
from quran_image_generator.api import execute_request
from quran_image_generator.references import ReferenceError


def test_concurrent_jobs_and_verified_warm_reuse(tmp_path, monkeypatch):
    data = fixture_request(tmp_path)
    data["asset_cache_directory"] = str(tmp_path / "asset cache")
    cold = execute_request(data).to_dict()
    assert cold["status"] == "complete"
    monkeypatch.setattr(
        api,
        "render_layer",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Warm export must reuse PNGs")
        ),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: execute_request(data).to_dict(), range(2)))
    assert len({r["job_directory"] for r in results} | {cold["job_directory"]}) == 3
    assert all(r["assets"] == cold["assets"] for r in results)
    assert not list((tmp_path / "output with spaces").glob(".pending-*"))


def test_cancel_and_deadline_clean_staging(tmp_path):
    data = fixture_request(tmp_path)
    calls = []

    def progress(event):
        calls.append(event.phase)

    response = execute_request(
        data, progress=progress, cancelled=lambda: "render" in calls
    ).to_dict()
    assert response["error"]["code"] == "cancelled"
    assert len(response["cues"]) == 2 and not response["assets"]
    assert not list((tmp_path / "output with spaces").glob("*"))
    assert (
        execute_request(data, deadline_seconds=0.000001).payload["error"]["code"]
        == "deadline_exceeded"
    )


def test_per_cue_native_failure_retains_errors_and_no_orphans(tmp_path, monkeypatch):
    data = fixture_request(tmp_path)
    data["cues"][1]["spans"][0].update(surah=31, ayah=11, word_start=1, word_end=3)
    original = api.render_layer

    def failure(scene, plan, *args, **kwargs):
        if plan.layer.text.startswith("هَٰذَا"):
            raise ReferenceError("missing_asset", "Required test asset failed")
        return original(scene, plan, *args, **kwargs)

    monkeypatch.setattr(api, "render_layer", failure)
    result = execute_request(data).to_dict()
    assert result["status"] == "failed" and not result["assets"]
    assert not list((tmp_path / "output with spaces").glob("*"))
    data["error_mode"] = "per_cue"
    result = execute_request(data).to_dict()
    assert result["status"] == "partial" and len(result["assets"]) == 1
    assert result["cues"][1]["error"]["code"] == "missing_asset"
    assert len(list(Path(result["job_directory"]).glob("*.png"))) == 1


def test_cache_corruption_and_visual_change_invalidate(tmp_path):
    data = fixture_request(tmp_path)
    data["asset_cache_directory"] = str(tmp_path / "cache")
    first = execute_request(data).to_dict()
    changed = deepcopy(data)
    changed["canvas"] = {"width": 1080, "height": 1920}
    assert (
        execute_request(changed).payload["assets"][0]["asset_id"]
        != first["assets"][0]["asset_id"]
    )
    asset = first["assets"][0]
    (tmp_path / "cache" / asset["path"]).write_bytes(b"broken")
    result = execute_request(data).to_dict()
    assert result["cues"][0]["error"]["code"] == "corrupt_asset_cache"
    assert result["status"] == "failed"
