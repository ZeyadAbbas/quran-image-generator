import json
from pathlib import Path

import pytest
import requests

from quran_image_generator.layout import TextMetrics
from quran_image_generator.settings import Dimensions, Settings

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_json_fixture():
    def load(name):
        with (FIXTURES_DIR / name).open(encoding="utf-8") as fixture_file:
            return json.load(fixture_file)

    return load


@pytest.fixture(autouse=True)
def block_external_http(monkeypatch):
    def blocked_request(*args, **kwargs):
        pytest.fail("Tests must not make external HTTP requests")

    monkeypatch.setattr(requests.sessions.Session, "request", blocked_request)


class FakeMeasurer:
    def measure(self, text, style):
        return TextMetrics(len(text) * 10, 12, 12, 0)


@pytest.fixture
def fake_measurer():
    return FakeMeasurer()


@pytest.fixture
def settings_factory(tmp_path):
    def make_settings(**overrides):
        values = {
            "source_path": tmp_path / "config.yaml",
            "output_path": tmp_path,
            "resolution": Dimensions(300, 200),
            "background_image": None,
            "background_color": "#000000",
            "quran_font": "Fixture Quran",
            "quran_color": "#FFFFFF",
            "quran_font_size": 24,
            "quran_x_position": "center",
            "quran_max_width": 1_000,
            "quran_line_spacing": 5,
            "quran_word_spacing": 1,
            "quran_letter_spacing": 0.0,
            "quran_translation_spacing": 30,
            "translations": (),
            "translation_color": "#FFFFFF",
            "translation_font_size": 18,
            "translation_x_position": "center",
            "translation_max_width": 1_000,
            "translation_language_spacing": 7,
            "translation_line_spacing": 3,
            "translation_word_spacing": 1,
            "translation_letter_spacing": 0.0,
            "show_verse_numbers": False,
            "verse_number_resolution": Dimensions(55, 55),
            "verse_number_x_offset": 0,
            "verse_number_y_offset": 0,
            "space_between_verses": 20,
            "generate_random_verses": False,
            "total_y_offset": 0,
            "upload": False,
            "username": "",
            "password": "",
            "post_method": "",
        }
        values.update(overrides)
        return Settings(**values)

    return make_settings
