import builtins
from pathlib import Path
from types import SimpleNamespace

import pytest

import quran_image_generator as generator_module
from line import Line
from quran_image_generator import QuranImageGenerator


def make_generator(monkeypatch, chapter=1, starting_verse=1, ending_verse=2):
    monkeypatch.setattr(
        generator_module.config, "translation_languages", lambda: {}
    )
    return QuranImageGenerator(chapter, starting_verse, ending_verse)


def test_formats_inclusive_verse_keys(monkeypatch):
    generator = make_generator(monkeypatch, chapter=2, starting_verse=3, ending_verse=5)

    assert generator.format_verse_keys() == ["2:3", "2:4", "2:5"]


def test_api_call_builds_expected_request(monkeypatch, load_json_fixture):
    payload = load_json_fixture("verse_one_translation.json")
    captured = {}
    monkeypatch.setattr(
        generator_module.config,
        "translation_languages",
        lambda: {"131": {}, "31": {}},
    )

    def fake_get(uri, **kwargs):
        captured["uri"] = uri
        captured.update(kwargs)
        return SimpleNamespace(json=lambda: payload)

    monkeypatch.setattr(generator_module.requests, "get", fake_get)
    generator = QuranImageGenerator(1, 1, 1)

    assert generator.api_call("verses/by_key/1:1") == payload
    assert captured == {
        "uri": "https://api.quran.com/api/v4/verses/by_key/1:1",
        "headers": {"Accept": "application/json"},
        "data": {},
        "params": {
            "translations": "131, 31",
            "words": 1,
            "word_fields": "text_uthmani",
        },
    }


def test_generation_flow_uses_fakes(
    monkeypatch, tmp_path, load_json_fixture
):
    verse_payload = load_json_fixture("verse_no_translations.json")
    chapter_payload = load_json_fixture("chapter.json")
    endpoints = []
    saved_paths = []
    drawn_text = []

    class FakeVerse:
        def __init__(self, payload):
            self.number = payload["verse"]["verse_number"]
            self.height = 10
            self.lines = [Line("بِسْمِ", 30, 10)]
            self.translations = []

        def set_draw_settings(self, draw):
            draw.font = "Fixture Quran"

    class FakeImage:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def save(self, filename):
            saved_paths.append(filename)

    class FakeDrawing:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def text(self, x, y, text):
            drawn_text.append((x, y, text))

        def __call__(self, image):
            return None

    generator = make_generator(monkeypatch, ending_verse=1)

    def fake_api_call(endpoint):
        endpoints.append(endpoint)
        if endpoint.startswith("verses/by_key/"):
            return verse_payload
        return chapter_payload

    monkeypatch.setattr(generator, "api_call", fake_api_call)
    monkeypatch.setattr(generator_module, "Verse", FakeVerse)
    monkeypatch.setattr(generator_module, "Image", FakeImage)
    monkeypatch.setattr(generator_module, "Drawing", FakeDrawing)

    config_values = {
        "resolution": (300, 200),
        "background_color": "xc:#000000",
        "background_image": "",
        "space_between_verses": 20,
        "total_y_offset": 0,
        "quran_x_position": "center",
        "quran_line_spacing": 5,
        "verse_numbers_visible": False,
        "output_path": str(tmp_path),
    }
    for name, value in config_values.items():
        monkeypatch.setattr(
            generator_module.config, name, lambda value=value: value
        )

    generator.fetch_verses()
    generator.create_image()

    expected_path = str(tmp_path / "Al-Fatihah 1.png")
    assert generator.image_path == expected_path
    assert saved_paths == [expected_path]
    assert endpoints == ["verses/by_key/1:1", "chapters/1"]
    assert drawn_text == [(135, 105, "بِسْمِ")]


def test_instagram_dependency_is_only_required_when_posting(monkeypatch):
    generator = make_generator(monkeypatch, ending_verse=1)
    monkeypatch.setattr(generator_module.config, "post_method", lambda: "insta_post")
    real_import = builtins.__import__

    def import_without_instagram(name, *args, **kwargs):
        if name == "instagrapi":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_instagram)

    with pytest.raises(RuntimeError, match="pip install.*instagram"):
        generator.post("unused", "unused")
