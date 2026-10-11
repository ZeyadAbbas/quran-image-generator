import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import asdict

import jsonschema
import pytest
from test_bindings import fixture_dataset

from quran_image_generator.api import execute_request
from quran_image_generator.contract_schema import REQUEST_SCHEMA, RESPONSE_SCHEMA
from quran_image_generator.references import CorpusIdentity, SourceSpan
from quran_image_generator.requests import BatchRequest, CueRequest
from quran_image_generator.resources import asset_path


def fixture_request(tmp_path, operation="render_batch"):
    return {
        "schema_version": 1,
        "request_id": "test-طلب",
        "operation": operation,
        "source_corpus": asdict(CorpusIdentity()),
        "canvas": {"width": 576, "height": 1024},
        "output_directory": str(tmp_path / "output with spaces"),
        "cues": [
            {
                "cue_id": "a",
                "spans": [{"surah": 31, "ayah": 9, "word_start": 1, "word_end": 5}],
                "metadata": {"start_seconds": 0.4, "end_seconds": 3.4},
            },
            {
                "cue_id": "b",
                "spans": [{"surah": 31, "ayah": 9, "word_start": 1, "word_end": 5}],
            },
        ],
    }


def test_machine_contract_render_repeats_and_checksums(tmp_path):
    request = fixture_request(tmp_path)
    response = execute_request(request).to_dict()
    assert response["status"] == "complete"
    assert len(response["cues"]) == 2 and len(response["assets"]) == 1
    assert response["cues"][0]["metadata"] == request["cues"][0]["metadata"]
    assert response["cues"][0]["asset_ids"] == response["cues"][1]["asset_ids"]
    for asset in response["assets"]:
        path = __import__("pathlib").Path(response["job_directory"]) / asset["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]
    jsonschema.validate(request, REQUEST_SCHEMA)
    jsonschema.validate(response, RESPONSE_SCHEMA)


@pytest.mark.parametrize(
    "change,code",
    [
        (dict(schema_version=2), "unsupported_version"),
        (dict(unknown=1), "invalid_request"),
        (dict(canvas={"width": True, "height": 1024}), "invalid_request"),
    ],
)
def test_strict_errors(tmp_path, change, code):
    response = execute_request({**fixture_request(tmp_path), **change}).to_dict()
    assert response["status"] == "failed" and response["error"]["code"] == code


def test_invalid_duplicate_corpus_and_no_partial_success(tmp_path):
    data = fixture_request(tmp_path)
    duplicate = deepcopy(data)
    duplicate["cues"][1]["cue_id"] = "a"
    assert execute_request(duplicate).payload["error"]["code"] == "duplicate_cue_id"
    data["source_corpus"]["sha256"] = "0" * 64
    assert execute_request(data).payload["error"]["code"] == "unsupported_corpus"
    data = fixture_request(tmp_path)
    data["cues"][1]["spans"][0]["word_end"] = 999
    result = execute_request(data).to_dict()
    assert result["status"] == "failed" and result["assets"] == []
    assert not (tmp_path / "output with spaces").exists()


def test_layout_and_reviewed_english_use_public_python_surface(tmp_path):
    batch = BatchRequest("typed", (CueRequest("c", (SourceSpan(31, 9, 1, 5),)),))
    assert execute_request(batch.to_request()).payload["status"] == "complete"
    request = fixture_request(tmp_path, "layout")
    request["translation_dataset"] = fixture_dataset().to_dict()
    for cue in request["cues"]:
        cue.update(translation_policy="required", translation_binding_id="31-9-prefix")
    result = execute_request(request).to_dict()
    assert result["cues"][0]["translation"]["binding"]["review_status"] == "approved"
    assert len(result["cues"][0]["layers"]) == 2
    assert result["assets"] == [] and not (tmp_path / "output with spaces").exists()


def test_cli_file_outside_checkout_matches_python(tmp_path):
    data = fixture_request(tmp_path, "layout")
    path = tmp_path / "request with spaces.json"
    path.write_text(json.dumps(data), "utf-8")
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
        encoding="utf-8",
    )
    assert result.returncode == 0 and result.stderr == ""
    assert json.loads(result.stdout) == execute_request(data).to_dict()


def test_published_schemas_match_code():
    assert (
        json.loads(asset_path("schemas", "request-v1.json").read_text())
        == REQUEST_SCHEMA
    )
    assert (
        json.loads(asset_path("schemas", "response-v1.json").read_text())
        == RESPONSE_SCHEMA
    )
