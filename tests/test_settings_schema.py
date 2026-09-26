from __future__ import annotations

import os
from dataclasses import replace

import pytest
import yaml

from quran_image_generator.models import TranslationResource
from quran_image_generator.resources import asset_path
from quran_image_generator.settings import (
    DEFAULTS,
    SETTING_SPECS,
    load_settings,
    save_settings,
    settings_from_mapping,
    settings_help_text,
    settings_to_mapping,
)


def test_schema_is_complete_unique_and_documented():
    keys = [spec.key for spec in SETTING_SPECS]

    assert len(keys) == len(set(keys))
    assert set(keys) == set(DEFAULTS)
    assert all(
        spec.label.strip()
        and spec.description.strip()
        and spec.effect.strip()
        and spec.format_hint.strip()
        for spec in SETTING_SPECS
    )
    help_text = settings_help_text()
    assert all(spec.label in help_text for spec in SETTING_SPECS)
    assert "background image's dimensions" in help_text


def test_mapping_and_file_parsers_share_the_same_model(tmp_path):
    values = {
        "resolution": "640 x 480",
        "background color": "#123456",
        "quran font size": 29,
        "translation languages": [{"id": 20}, {"slug": "a-slug"}],
    }
    path = tmp_path / "same.yaml"
    path.write_text(yaml.safe_dump(values), encoding="utf-8")

    from_file = load_settings(path, create_output_dir=False)
    from_mapping = settings_from_mapping(values, source_path=path)

    assert from_file == from_mapping


def test_background_sized_resolution_round_trips_as_bg(tmp_path):
    background = tmp_path / "background.svg"
    background.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"/>',
        encoding="utf-8",
    )
    source = tmp_path / "source.yaml"
    settings = settings_from_mapping(
        {"background image": "background.svg", "resolution": "bg"},
        source_path=source,
    )

    assert settings.resolution.as_tuple() == (320, 180)
    assert settings.resolution_from_background
    assert settings_to_mapping(settings)["resolution"] == "bg"


def test_config_round_trip_preserves_paths_selectors_order_and_font_sizes(tmp_path):
    background = tmp_path / "assets with spaces" / "background.png"
    quran_font = tmp_path / "assets with spaces" / "quran.ttf"
    translation_font = tmp_path / "assets with spaces" / "translation.ttf"
    background.parent.mkdir()
    background.write_bytes(b"image")
    quran_font.write_bytes(b"font")
    translation_font.write_bytes(b"font")
    source = tmp_path / "source.yaml"
    values = {
        "output path": "generated images",
        "background image": str(background),
        "quran font": str(quran_font),
        "translation font size": 18,
        "translation languages": [
            {"id": 10, "font": str(translation_font), "font size": 21},
            {"slug": "translator-two", "font size": 22},
            {"language": "fr"},
        ],
    }
    settings = settings_from_mapping(values, source_path=source)
    destination = tmp_path / "saved" / "portable.yaml"

    saved = save_settings(settings, destination)
    reloaded = load_settings(destination, create_output_dir=False)

    assert settings_to_mapping(saved) == settings_to_mapping(reloaded)
    assert [item.selector.kind for item in reloaded.translations] == [
        "id",
        "slug",
        "language",
    ]
    assert [item.font_size for item in reloaded.translations] == [21, 22, 18]
    yaml_text = destination.read_text(encoding="utf-8")
    assert str(tmp_path) not in yaml_text
    assert "source_path" not in yaml_text
    assert "resource_id" not in yaml_text


def test_runtime_resources_and_auto_bundled_fonts_are_not_serialized(tmp_path):
    source = tmp_path / "config.yaml"
    configured = settings_from_mapping(
        {
            "quran font": str(asset_path("fonts", "quran_font.ttf")),
            "translation languages": [{"id": 42}],
        },
        source_path=source,
    )
    resource = TranslationResource(
        "42",
        "example",
        "Example translation",
        "Example author",
        "Chinese",
        "zh",
    )
    runtime = replace(
        configured,
        translations=(configured.translations[0].resolve(resource),),
    )

    mapping = settings_to_mapping(runtime, destination_path=source)

    assert mapping["quran font"] == "assets/fonts/quran_font.ttf"
    assert mapping["translation languages"] == [{"id": 42}]
    serialized = yaml.safe_dump(mapping)
    assert str(asset_path("fonts", "multilingual_fonts", "zh.ttf")) not in serialized
    assert "Example author" not in serialized


def test_config_save_never_includes_environment_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("QF_CLIENT_SECRET", "qf-secret-sentinel")
    monkeypatch.setenv("QIG_INSTAGRAM_PASSWORD", "instagram-secret-sentinel")
    settings = settings_from_mapping({}, source_path=tmp_path / "source.yaml")
    destination = tmp_path / "saved.yaml"

    save_settings(settings, destination)

    text = destination.read_text(encoding="utf-8")
    assert "qf-secret-sentinel" not in text
    assert "instagram-secret-sentinel" not in text
    assert "QF_CLIENT_SECRET" not in text
    assert "QIG_INSTAGRAM_PASSWORD" not in text


def test_atomic_config_replace_failure_preserves_old_file(monkeypatch, tmp_path):
    destination = tmp_path / "settings.yaml"
    destination.write_text("old: file\n", encoding="utf-8")
    settings = settings_from_mapping({}, source_path=destination)
    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(OSError()))

    with pytest.raises(OSError):
        save_settings(settings, destination)

    assert destination.read_text(encoding="utf-8") == "old: file\n"
    assert list(tmp_path.glob(".settings.yaml.*.tmp")) == []
