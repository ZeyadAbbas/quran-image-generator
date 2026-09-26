"""Temporary compatibility facade for the legacy configuration getters.

New code should accept a :class:`settings.Settings` instance directly. This
module keeps the current renderer working until that dependency injection is
completed, but deliberately performs no work at import time.
"""

from __future__ import annotations

from pathlib import Path

from settings import DEFAULTS as _DEFAULTS
from settings import Settings, load_settings

DEFAULTS = _DEFAULTS
_settings: Settings | None = None


def load_config(
    config_path: str | Path = "config.yaml", *, create_output_dir: bool = True
) -> Settings:
    """Explicitly load, validate, and activate settings for legacy callers."""

    global _settings
    _settings = load_settings(config_path, create_output_dir=create_output_dir)
    return _settings


def set_settings(settings: Settings) -> None:
    """Activate an already-loaded settings object for legacy consumers."""

    global _settings
    _settings = settings


def get_settings() -> Settings:
    """Return active settings or explain how the caller should initialize them."""

    if _settings is None:
        raise RuntimeError("Settings are not loaded. Call read_config.load_config(path) first.")
    return _settings


def output_path() -> str:
    return str(get_settings().output_path)


def background_image() -> str:
    path = get_settings().background_image
    return str(path) if path is not None else ""


def resolution() -> tuple[int, int]:
    return get_settings().resolution.as_tuple()


def background_color() -> str:
    return f"xc:{get_settings().background_color}"


def quran_font() -> str:
    return str(get_settings().quran_font)


def quran_color() -> str:
    return get_settings().quran_color


def quran_font_size() -> int:
    return get_settings().quran_font_size


def quran_x_position() -> int | str:
    return get_settings().quran_x_position


def translation_font_size() -> int:
    return get_settings().translation_font_size


def translation_languages() -> dict[str, dict[str, str | int]]:
    return {
        translation.resource_id: {
            "font": str(translation.font),
            "font_size": translation.font_size,
        }
        for translation in get_settings().translations
    }


def translation_color() -> str:
    return get_settings().translation_color


def quran_max_width() -> int:
    return get_settings().quran_max_width


def quran_line_spacing() -> int:
    return get_settings().quran_line_spacing


def quran_word_spacing() -> str:
    return " " * get_settings().quran_word_spacing


def quran_letter_spacing() -> float:
    return get_settings().quran_letter_spacing


def translation_max_width() -> int:
    return get_settings().translation_max_width


def translation_line_spacing() -> int:
    return get_settings().translation_line_spacing


def translation_word_spacing() -> str:
    return " " * get_settings().translation_word_spacing


def translation_letter_spacing() -> float:
    return get_settings().translation_letter_spacing


def translation_language_spacing() -> int:
    return get_settings().translation_language_spacing


def translation_x_position() -> int | str:
    return get_settings().translation_x_position


def quran_translation_spacing() -> int:
    return get_settings().quran_translation_spacing


def space_between_verses() -> int:
    return get_settings().space_between_verses


def verse_numbers_visible() -> bool:
    return get_settings().show_verse_numbers


def verse_number_resolution() -> tuple[int, int]:
    return get_settings().verse_number_resolution.as_tuple()


def verse_number_x_offset() -> int:
    return get_settings().verse_number_x_offset


def verse_number_y_offset() -> int:
    return get_settings().verse_number_y_offset


def generate_random_verses() -> bool:
    return get_settings().generate_random_verses


def total_y_offset() -> int:
    return get_settings().total_y_offset


def upload() -> bool | str:
    return get_settings().upload


def username() -> str:
    return get_settings().username


def password() -> str:
    return get_settings().password


def post_method() -> str:
    return get_settings().post_method
