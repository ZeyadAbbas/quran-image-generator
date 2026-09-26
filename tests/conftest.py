import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests


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


class FakeImage:
    def __init__(self, **kwargs):
        self.width = kwargs.get("width", 1)
        self.height = kwargs.get("height", 1)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FakeDrawing:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def get_font_metrics(self, image, text):
        return SimpleNamespace(text_width=len(text) * 10, text_height=12)


@pytest.fixture
def fake_font_metrics(monkeypatch):
    import translation
    import verse

    monkeypatch.setattr(verse, "Image", FakeImage)
    monkeypatch.setattr(verse, "Drawing", FakeDrawing)
    monkeypatch.setattr(translation, "Image", FakeImage)
    monkeypatch.setattr(translation, "Drawing", FakeDrawing)


@pytest.fixture
def layout_config(monkeypatch):
    import read_config as config

    languages = {
        "131": {"font": "Fixture Sans", "font_size": 18},
        "31": {"font": "Fixture Sans", "font_size": 18},
    }
    values = {
        "quran_font": "Fixture Quran",
        "quran_font_size": 24,
        "quran_color": "#ffffff",
        "quran_letter_spacing": 0,
        "quran_max_width": 1_000,
        "quran_word_spacing": " ",
        "quran_x_position": "center",
        "quran_line_spacing": 5,
        "verse_number_resolution": (0, 0),
        "verse_number_x_offset": 0,
        "translation_languages": languages,
        "translation_color": "#ffffff",
        "translation_letter_spacing": 0,
        "translation_max_width": 1_000,
        "translation_word_spacing": " ",
        "translation_line_spacing": 3,
        "translation_language_spacing": 7,
    }

    for name, value in values.items():
        monkeypatch.setattr(config, name, lambda value=value: value)

    return values
