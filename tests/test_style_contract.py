import copy
import json
import os
import subprocess
import sys

import pytest
from test_api import fixture_request

from quran_image_generator.api import capabilities, execute_request, inspect_request
from quran_image_generator.caption_editor import STYLE_FIELDS, default_styles
from quran_image_generator.resources import asset_path


def profile(styles):
    return {"id": "plain", "revision": "1", "approval": "approved", "styles": styles, "provenance": {}}


def test_all_fields_have_shared_descriptors_and_real_role_defaults():
    descriptor = capabilities()["style_contract"]
    assert descriptor["descriptor_version"] == 1
    assert set(descriptor["fields"]) == set(STYLE_FIELDS)
    for role, defaults in descriptor["role_defaults"].items():
        assert defaults == default_styles(role)
    for spec in descriptor["fields"].values():
        assert {"type", "default", "x-units", "x-scaling", "x-roles"} <= spec.keys()
    assert descriptor["fields"]["outline_width"]["maximum"] == 8


def test_multiple_schema_field_errors_before_any_output(tmp_path):
    data = fixture_request(tmp_path)
    data["profile"] = profile({"arabic": {"alignment": "justify", "outline_width": 100, "unknown": 1}})
    result = execute_request(data).to_dict()
    diagnostics = result["error"]["details"]["diagnostics"]
    assert {d["path"] for d in diagnostics} == {
        "/profile/styles/arabic/alignment", "/profile/styles/arabic/outline_width", "/profile/styles/arabic/unknown"}
    assert not (tmp_path / "output with spaces").exists()


def test_inspection_resolves_explicit_disabled_defaults_and_units(tmp_path):
    data = fixture_request(tmp_path)
    data["profile"] = profile({"arabic": {"enabled": False, "outline_width": 2}})
    data["canvas"]["width"] = 1152
    result = inspect_request(data).to_dict()
    layer = result["cues"][0]["inspection"]["layers"][0]
    assert layer["status"] == "disabled"
    assert layer["effective"]["font_size"] == 30
    assert layer["origins"]["font_size"] == "default"
    assert layer["origins"]["enabled"] == "explicit"
    assert layer["resolved_pixels"]["outline_width"] == 4
    assert result["assets"] == [] and not (tmp_path / "output with spaces").exists()
    assert data["operation"] == "render_batch"


def test_resolved_default_minimum_has_exact_field_path(tmp_path):
    data = fixture_request(tmp_path, "inspect")
    data["profile"] = profile({"arabic": {"font_size": 10}})
    result = execute_request(data).to_dict()
    details = result["cues"][0]["error"]["details"]
    assert details["path"] == "/profile/styles/arabic/font_size"
    assert details["resolved_minimum"] == 12
    assert details["cue_id"] == "a"
    data["profile"]["styles"]["arabic"]["min_font_size"] = 8
    assert execute_request(data).payload["status"] == "complete"


def test_legacy_pixels_and_cli_inspection(tmp_path):
    data = fixture_request(tmp_path)
    legacy = execute_request(data).to_dict()
    explicit = copy.deepcopy(data)
    explicit["profile"] = profile({"arabic": default_styles("arabic")})
    result = execute_request(explicit).to_dict()
    assert result["assets"][0]["sha256"] == legacy["assets"][0]["sha256"]
    data["operation"] = "inspect"
    request = tmp_path / "inspect.json"
    request.write_text(json.dumps(data), encoding="utf-8")
    output = subprocess.run([sys.executable, "-m", "quran_image_generator.machine_cli", "--request", str(request)],
                            cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(asset_path().parent.parent)},
                            capture_output=True, encoding="utf-8")
    assert output.returncode == 0, output.stderr
    assert json.loads(output.stdout) == execute_request(data).to_dict()


@pytest.mark.parametrize("name,value", [("opacity", True), ("anchor", [0.5]), ("region", [0.1, 0.2, 0.1, 0.8])])
def test_python_and_json_reject_invalid_style_geometry(tmp_path, name, value):
    data = fixture_request(tmp_path, "inspect")
    data["profile"] = profile({"arabic": {name: value}})
    result = execute_request(data).to_dict()
    assert result["status"] == "failed"
