import json
from dataclasses import asdict
from pathlib import Path

import pytest
from test_api import fixture_request

from quran_image_generator.api import execute_request
from quran_image_generator.excerpts import ExcerptRequest, select_excerpt
from quran_image_generator.profiles import creator_profile
from quran_image_generator.references import SourceSpan
from quran_image_generator.scenes import caption_scene


def test_preflight_actual_inputs_and_bundled_fonts(tmp_path):
    data = fixture_request(tmp_path, "preflight")
    result = execute_request(data).to_dict()
    assert (
        result["preflight"]["ready"]
        and len(result["preflight"]["checks"]["assets"]) == 4
    )
    assert result["assets"] == [] and not list(
        (tmp_path / "output with spaces").iterdir()
    )
    data["translation_snapshot"] = {
        "directory": str(tmp_path / "cache"),
        "sha256": "0" * 64,
    }
    assert execute_request(data).payload["error"]["code"] == "offline_translation_miss"


def test_creator_profile_python_json_roundtrip_is_review_required(tmp_path):
    data = fixture_request(tmp_path, "layout")
    excerpt = select_excerpt(ExcerptRequest("a", (SourceSpan(31, 9, 1, 5),)))
    data["profile"] = asdict(creator_profile(caption_scene(excerpt)))
    result = execute_request(data).to_dict()
    assert result["status"] == "needs_review"
    data["require_approved_profile"] = True
    assert execute_request(data).payload["cues"][0]["error"]["code"] == "profile_review"


@pytest.mark.parametrize(
    "name",
    [
        "arabic-batch",
        "layout-only",
        "persistent-and-basmala",
        "reviewed-english",
        "offline-snapshot",
        "creator-preview",
    ],
)
def test_copyable_installed_contract_examples(name, tmp_path):
    root = Path(__file__).resolve().parents[1] / "examples" / "captions"
    data = json.loads((root / f"{name}.json").read_text("utf-8"))
    data["operation"] = "preflight"
    data["output_directory"] = str(tmp_path)
    result = execute_request(data, asset_root=root).to_dict()
    expected = "needs_review" if name == "creator-preview" else "complete"
    assert result["status"] == expected, result
    assert result["assets"] == [] and not list(tmp_path.iterdir())
