from pathlib import Path

import yaml

from quran_image_generator.rendering import VERSE_NUMBERS_FOLDER
from quran_image_generator.resources import ASSETS_DIRECTORY, asset_path
from quran_image_generator.settings import load_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_required_runtime_assets_live_under_the_package_once():
    required = (
        asset_path("fonts", "quran_font.ttf"),
        asset_path("verse_numbers", "1.png"),
        asset_path("verse_numbers", "286.png"),
    )

    assert ASSETS_DIRECTORY.is_absolute()
    assert VERSE_NUMBERS_FOLDER == asset_path("verse_numbers")
    assert all(path.is_file() for path in required)
    assert not asset_path("verse_bounds.txt").exists()
    assert not asset_path("translation_codes", "translation_codes.yaml").exists()
    assert not (PROJECT_ROOT / "assets").exists()


def test_legacy_asset_font_path_resolves_from_an_external_config(tmp_path):
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "quran font": "assets/fonts/quran_font.ttf",
                "translation languages": "",
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(config_path, create_output_dir=False)

    assert settings.quran_font == asset_path("fonts", "quran_font.ttf")
