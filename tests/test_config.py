from pathlib import Path

import pytest

import read_config as config


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("640 x 480", (640, 480)),
        ("640x480", (640, 480)),
        ("invalid", (1080, 1080)),
        ("640 x nope", (1080, 1080)),
    ],
)
def test_resolution_validation(monkeypatch, configured, expected):
    monkeypatch.setattr(config, "config", {"resolution": configured})

    assert config.resolution() == expected


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("#12abEF", "xc:#12abEF"),
        ("12abEF", "xc:#12abEF"),
        ("not-a-color", "xc:#000000"),
    ],
)
def test_background_color_validation(monkeypatch, configured, expected):
    monkeypatch.setattr(config, "config", {"background color": configured})

    assert config.background_color() == expected


def test_invalid_font_size_uses_default(monkeypatch):
    monkeypatch.setattr(config, "config", {"quran font size": "large"})

    assert config.quran_font_size() == config.DEFAULTS["quran font size"]


def test_blank_output_path_creates_default_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "config", {"output path": ""})

    assert config.output_path() == "outputs"
    assert (tmp_path / "outputs").is_dir()


@pytest.mark.xfail(
    strict=True,
    reason="Known configuration bug tracked by #7: valid output paths are discarded",
)
def test_valid_output_path_is_preserved(monkeypatch, tmp_path):
    output_path = tmp_path / "images"
    output_path.mkdir()
    monkeypatch.setattr(config, "config", {"output path": str(output_path)})

    assert Path(config.output_path()) == output_path
