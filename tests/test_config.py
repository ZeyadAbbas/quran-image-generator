from pathlib import Path

import pytest
import yaml

from quran_image_generator import read_config as config
from quran_image_generator.settings import SettingsValidationError


def write_config(tmp_path, values):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(values), encoding="utf-8")
    return config_path


@pytest.mark.parametrize("configured", ["640 x 480", "640x480", [640, 480]])
def test_resolution_validation(tmp_path, configured):
    config.load_config(
        write_config(tmp_path, {"resolution": configured}), create_output_dir=False
    )

    assert config.resolution() == (640, 480)


@pytest.mark.parametrize("configured", ["invalid", "640 x nope", [640, -1]])
def test_invalid_resolution_is_reported(tmp_path, configured):
    with pytest.raises(SettingsValidationError) as caught:
        config.load_config(
            write_config(tmp_path, {"resolution": configured}),
            create_output_dir=False,
        )

    assert [issue.field for issue in caught.value.issues] == ["resolution"]


@pytest.mark.parametrize("configured", ["#12abEF", "12abEF"])
def test_background_color_validation(tmp_path, configured):
    config.load_config(
        write_config(tmp_path, {"background color": configured}),
        create_output_dir=False,
    )

    assert config.background_color() == "xc:#12ABEF"


def test_invalid_background_color_is_reported(tmp_path):
    with pytest.raises(SettingsValidationError) as caught:
        config.load_config(
            write_config(tmp_path, {"background color": "not-a-color"}),
            create_output_dir=False,
        )

    assert [issue.field for issue in caught.value.issues] == ["background color"]


def test_invalid_font_size_is_reported(tmp_path):
    with pytest.raises(SettingsValidationError) as caught:
        config.load_config(
            write_config(tmp_path, {"quran font size": "large"}),
            create_output_dir=False,
        )

    assert [issue.field for issue in caught.value.issues] == ["quran font size"]


def test_blank_output_path_creates_default_directory(tmp_path):
    config.load_config(write_config(tmp_path, {"output path": ""}))

    expected = tmp_path / "outputs"
    assert Path(config.output_path()) == expected
    assert expected.is_dir()


def test_valid_output_path_is_preserved(tmp_path):
    output_path = tmp_path / "images"
    output_path.mkdir()
    config.load_config(write_config(tmp_path, {"output path": str(output_path)}))

    assert Path(config.output_path()) == output_path
