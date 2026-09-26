"""Typed, explicit configuration loading for the image generator.

The public entry point is :func:`load_settings`.  Importing this module never
reads configuration, inspects images, or creates directories.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import get_close_matches
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import yaml

Position = int | Literal["center"]
UploadMode = bool | Literal["ask"]


DEFAULTS: Mapping[str, Any] = MappingProxyType(
    {
        "output path": "outputs",
        "resolution": "1080 x 1080",
        "background image": "",
        "background color": "000000",
        "quran font": "Arial",
        "quran color": "FFFFFF",
        "quran font size": 34,
        "quran x position": 30,
        "quran maximum width": 700,
        "quran line spacing": 30,
        "quran word spacing": 6,
        "quran letter spacing": -0.1,
        "quran and translation spacing": 30,
        "translation languages": "",
        "translation color": "FFFFFF",
        "translation font size": 16,
        "translation x position": 40,
        "translation maximum width": 650,
        "translation language spacing": 10,
        "translation line spacing": 10,
        "translation word spacing": 1,
        "translation letter spacing": 0.0,
        "show verse numbers": False,
        "verse number resolution": "55 x 55",
        "verse number x offset": 10,
        "verse number y offset": -20,
        "space between verses": 70,
        "generate random verses": False,
        "total y offset": -10,
        "upload": False,
        "username": "",
        "password": "",
        "post method": "",
    }
)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One actionable problem found while loading settings."""

    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


class SettingsValidationError(ValueError):
    """Raised after every configuration field has been checked."""

    def __init__(self, issues: Sequence[ValidationIssue]):
        self.issues = tuple(issues)
        details = "\n".join(f"- {issue}" for issue in self.issues)
        super().__init__(f"Invalid settings:\n{details}")


@dataclass(frozen=True, slots=True)
class Dimensions:
    width: int
    height: int

    def as_tuple(self) -> tuple[int, int]:
        return self.width, self.height


@dataclass(frozen=True, slots=True)
class TranslationSettings:
    language_code: str
    resource_id: str
    font: Path | str
    font_size: int


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings shared by the CLI, renderer, and future GUI."""

    source_path: Path
    output_path: Path
    resolution: Dimensions
    background_image: Path | None
    background_color: str
    quran_font: Path | str
    quran_color: str
    quran_font_size: int
    quran_x_position: Position
    quran_max_width: int
    quran_line_spacing: int
    quran_word_spacing: int
    quran_letter_spacing: float
    quran_translation_spacing: int
    translations: tuple[TranslationSettings, ...]
    translation_color: str
    translation_font_size: int
    translation_x_position: Position
    translation_max_width: int
    translation_language_spacing: int
    translation_line_spacing: int
    translation_word_spacing: int
    translation_letter_spacing: float
    show_verse_numbers: bool
    verse_number_resolution: Dimensions
    verse_number_x_offset: int
    verse_number_y_offset: int
    space_between_verses: int
    generate_random_verses: bool
    total_y_offset: int
    upload: UploadMode
    username: str
    password: str
    post_method: str


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _raw_value(data: Mapping[str, Any], field: str) -> Any:
    value = data.get(field)
    return DEFAULTS[field] if _is_blank(value) else value


def _add_issue(
    issues: list[ValidationIssue], field: str, message: str
) -> None:
    issues.append(ValidationIssue(field, message))


def _parse_int(
    data: Mapping[str, Any],
    field: str,
    issues: list[ValidationIssue],
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw = _raw_value(data, field)
    if isinstance(raw, bool):
        value = None
    elif isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        try:
            value = int(raw.strip())
        except ValueError:
            value = None
    else:
        value = None

    default = int(DEFAULTS[field])
    if value is None:
        _add_issue(issues, field, "must be a whole number")
        return default
    if minimum is not None and value < minimum:
        _add_issue(issues, field, f"must be at least {minimum}")
        return default
    if maximum is not None and value > maximum:
        _add_issue(issues, field, f"must be at most {maximum}")
        return default
    return value


def _parse_float(
    data: Mapping[str, Any], field: str, issues: list[ValidationIssue]
) -> float:
    raw = _raw_value(data, field)
    if isinstance(raw, bool):
        value = None
    elif isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw.strip())
        except ValueError:
            value = None
    else:
        value = None

    if value is None or not isfinite(value):
        _add_issue(issues, field, "must be a finite number")
        return float(DEFAULTS[field])
    return value


def _parse_bool(
    data: Mapping[str, Any], field: str, issues: list[ValidationIssue]
) -> bool:
    raw = _raw_value(data, field)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    _add_issue(issues, field, "must be true or false")
    return bool(DEFAULTS[field])


def _parse_upload(
    data: Mapping[str, Any], issues: list[ValidationIssue]
) -> UploadMode:
    field = "upload"
    raw = _raw_value(data, field)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
        if normalized == "ask":
            return "ask"
    _add_issue(issues, field, "must be true, false, or 'ask'")
    return False


def _parse_text(
    data: Mapping[str, Any], field: str, issues: list[ValidationIssue]
) -> str:
    raw = data.get(field, DEFAULTS[field])
    if raw is None:
        return str(DEFAULTS[field])
    if isinstance(raw, str):
        return raw.strip()
    _add_issue(issues, field, "must be text")
    return str(DEFAULTS[field])


def _parse_color(
    data: Mapping[str, Any], field: str, issues: list[ValidationIssue]
) -> str:
    raw = _raw_value(data, field)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        _add_issue(
            issues,
            field,
            "was parsed as a number; quote hexadecimal colors, for example '001234'",
        )
        text = str(DEFAULTS[field]).lstrip("#")
    elif isinstance(raw, str):
        text = raw.strip()
    else:
        _add_issue(
            issues,
            field,
            "must be a quoted six-digit hexadecimal color such as '#FFFFFF'",
        )
        text = ""

    text = text.removeprefix("#")
    if len(text) != 6 or any(character not in "0123456789abcdefABCDEF" for character in text):
        if isinstance(raw, str):
            _add_issue(
                issues,
                field,
                "must be a six-digit hexadecimal color such as '#FFFFFF'",
            )
        text = str(DEFAULTS[field]).lstrip("#")
    return f"#{text.upper()}"


def _parse_position(
    data: Mapping[str, Any], field: str, issues: list[ValidationIssue]
) -> Position:
    raw = _raw_value(data, field)
    if isinstance(raw, str) and raw.strip().lower() == "center":
        return "center"
    if isinstance(raw, bool):
        value = None
    elif isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        try:
            value = int(raw.strip())
        except ValueError:
            value = None
    else:
        value = None
    if value is None or value < 0:
        _add_issue(issues, field, "must be 'center' or a non-negative whole number")
        return int(DEFAULTS[field])
    return value


def _resolve_path(raw: str, base_directory: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = base_directory / path
    return path.resolve(strict=False)


def _parse_output_path(
    data: Mapping[str, Any], base_directory: Path, issues: list[ValidationIssue]
) -> Path:
    field = "output path"
    raw = _raw_value(data, field)
    if not isinstance(raw, (str, Path)):
        _add_issue(issues, field, "must be a directory path")
        raw = str(DEFAULTS[field])
    output_path = _resolve_path(str(raw).strip(), base_directory)
    if output_path.exists() and not output_path.is_dir():
        _add_issue(issues, field, f"'{output_path}' exists but is not a directory")
    return output_path


def _parse_optional_file(
    data: Mapping[str, Any],
    field: str,
    base_directory: Path,
    issues: list[ValidationIssue],
) -> Path | None:
    raw = data.get(field)
    if _is_blank(raw):
        return None
    if not isinstance(raw, (str, Path)):
        _add_issue(issues, field, "must be a file path")
        return None
    path = _resolve_path(str(raw).strip(), base_directory)
    if not path.is_file():
        _add_issue(issues, field, f"file does not exist: {path}")
        return None
    return path


def _parse_font(
    data: Mapping[str, Any],
    field: str,
    base_directory: Path,
    issues: list[ValidationIssue],
) -> Path | str:
    raw = _raw_value(data, field)
    if not isinstance(raw, (str, Path)):
        _add_issue(issues, field, "must be 'Arial' or a .ttf/.otf file path")
        return str(DEFAULTS[field])
    text = str(raw).strip()
    if text.lower() == "arial":
        return "Arial"
    path = _resolve_path(text, base_directory)
    if path.suffix.lower() not in {".ttf", ".otf"}:
        _add_issue(issues, field, "must point to a .ttf or .otf font")
        return "Arial"
    if not path.is_file():
        _add_issue(issues, field, f"font file does not exist: {path}")
        return "Arial"
    return path


def _dimensions_from_value(
    raw: Any,
    field: str,
    default: str,
    issues: list[ValidationIssue],
) -> Dimensions:
    parts: Sequence[Any] | None = None
    if isinstance(raw, str):
        split = raw.lower().split("x")
        if len(split) == 2:
            parts = split
    elif isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        if len(raw) == 2:
            parts = raw

    values: list[int] = []
    if parts is not None:
        for part in parts:
            if isinstance(part, bool):
                values = []
                break
            try:
                value = int(str(part).strip())
            except ValueError:
                values = []
                break
            values.append(value)

    if len(values) != 2 or any(value <= 0 for value in values):
        _add_issue(
            issues,
            field,
            "must contain two positive dimensions, for example '1080 x 1080'",
        )
        defaults = [int(part.strip()) for part in default.split("x")]
        return Dimensions(*defaults)
    return Dimensions(*values)


def _parse_resolution(
    data: Mapping[str, Any],
    background_image: Path | None,
    issues: list[ValidationIssue],
) -> Dimensions:
    field = "resolution"
    raw = _raw_value(data, field)
    if isinstance(raw, str) and raw.strip().lower() == "bg":
        if background_image is None:
            _add_issue(issues, field, "cannot be 'bg' without a valid background image")
            return Dimensions(1080, 1080)
        try:
            from wand.exceptions import WandException
            from wand.image import Image as WandImage
        except ImportError:
            _add_issue(issues, field, "requires Wand/ImageMagick when set to 'bg'")
            return Dimensions(1080, 1080)
        try:
            with WandImage(filename=str(background_image)) as image:
                width, height = image.width, image.height
        except (OSError, WandException):
            _add_issue(issues, field, f"could not read dimensions from {background_image}")
            return Dimensions(1080, 1080)
        return Dimensions(width, height)
    return _dimensions_from_value(raw, field, str(DEFAULTS[field]), issues)


def _load_language_codes(
    language_codes_path: Path, issues: list[ValidationIssue]
) -> Mapping[str, str]:
    try:
        with language_codes_path.open("r", encoding="utf-8") as file:
            loaded = yaml.safe_load(file)
    except OSError as error:
        _add_issue(
            issues,
            "translation languages",
            f"could not read language catalog '{language_codes_path}': {error}",
        )
        return {}
    except yaml.YAMLError as error:
        _add_issue(
            issues,
            "translation languages",
            f"language catalog is malformed: {error}",
        )
        return {}
    if not isinstance(loaded, Mapping):
        _add_issue(issues, "translation languages", "language catalog must be a mapping")
        return {}
    return {str(code): str(resource_id) for code, resource_id in loaded.items()}


def _translation_entries(
    raw: Any, issues: list[ValidationIssue]
) -> list[tuple[str, Any, Any]]:
    field = "translation languages"
    if _is_blank(raw):
        return []
    if isinstance(raw, str):
        entries: Sequence[Any] = [item.strip() for item in raw.split(",") if item.strip()]
    elif isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        entries = raw
    else:
        _add_issue(
            issues,
            field,
            "must be a comma-separated string or a list of language entries",
        )
        return []

    parsed: list[tuple[str, Any, Any]] = []
    for index, entry in enumerate(entries):
        entry_field = f"{field}[{index}]"
        if isinstance(entry, Mapping):
            code = entry.get("code", "")
            font = entry.get("font")
            font_size = entry.get("font size", entry.get("font_size"))
        elif isinstance(entry, str):
            parts = [part.strip() for part in entry.split(":")]
            if len(parts) > 3:
                _add_issue(
                    issues,
                    entry_field,
                    "must use code, code:font, code:size, or code:font:size",
                )
                continue
            code = parts[0]
            font = None
            font_size = None
            if len(parts) == 2:
                try:
                    font_size = int(parts[1])
                except ValueError:
                    font = parts[1]
            elif len(parts) == 3:
                font = parts[1] or None
                font_size = parts[2]
        else:
            _add_issue(issues, entry_field, "must be text or a mapping")
            continue
        if not isinstance(code, str) or not code.strip():
            _add_issue(issues, entry_field, "must include a language code")
            continue
        parsed.append((code.strip(), font, font_size))
    return parsed


def _translation_font(
    raw: Any,
    language_code: str,
    base_directory: Path,
    application_directory: Path,
    field: str,
    issues: list[ValidationIssue],
) -> Path | str:
    if _is_blank(raw):
        multilingual_directory = application_directory / "assets" / "fonts" / "multilingual_fonts"
        for suffix in (".ttf", ".otf"):
            candidate = multilingual_directory / f"{language_code}{suffix}"
            if candidate.is_file():
                return candidate.resolve()
        return "Arial"
    if not isinstance(raw, (str, Path)):
        _add_issue(issues, field, "font must be 'Arial' or a .ttf/.otf file path")
        return "Arial"
    text = str(raw).strip()
    if text.lower() == "arial":
        return "Arial"
    path = _resolve_path(text, base_directory)
    if not path.exists() and Path(text).parent == Path("."):
        path = (application_directory / "assets" / "fonts" / text).resolve(strict=False)
    if path.suffix.lower() not in {".ttf", ".otf"}:
        _add_issue(issues, field, "font must point to a .ttf or .otf file")
        return "Arial"
    if not path.is_file():
        _add_issue(issues, field, f"font file does not exist: {path}")
        return "Arial"
    return path


def _parse_translations(
    data: Mapping[str, Any],
    base_directory: Path,
    application_directory: Path,
    default_font_size: int,
    language_codes_path: Path,
    issues: list[ValidationIssue],
) -> tuple[TranslationSettings, ...]:
    field = "translation languages"
    entries = _translation_entries(data.get(field), issues)
    if not entries:
        return ()
    if len(entries) > 3:
        _add_issue(issues, field, "supports at most three languages")
        entries = entries[:3]
    language_codes = _load_language_codes(language_codes_path, issues)
    translations: list[TranslationSettings] = []
    seen_codes: set[str] = set()
    for index, (language_code, raw_font, raw_font_size) in enumerate(entries):
        entry_field = f"{field}[{index}]"
        if language_code in seen_codes:
            _add_issue(issues, entry_field, f"duplicates language code '{language_code}'")
            continue
        seen_codes.add(language_code)
        resource_id = language_codes.get(language_code)
        if resource_id is None:
            _add_issue(issues, entry_field, f"unknown language code '{language_code}'")
            continue
        font = _translation_font(
            raw_font,
            language_code,
            base_directory,
            application_directory,
            f"{entry_field}.font",
            issues,
        )
        font_size = default_font_size
        if not _is_blank(raw_font_size):
            if isinstance(raw_font_size, bool):
                parsed_font_size = None
            else:
                try:
                    parsed_font_size = int(str(raw_font_size).strip())
                except ValueError:
                    parsed_font_size = None
            if parsed_font_size is None or parsed_font_size <= 0:
                _add_issue(issues, f"{entry_field}.font size", "must be a positive whole number")
            else:
                font_size = parsed_font_size
        translations.append(
            TranslationSettings(language_code, resource_id, font, font_size)
        )
    return tuple(translations)


def _load_yaml(config_path: Path) -> Mapping[str, Any]:
    try:
        with config_path.open("r", encoding="utf-8") as file:
            loaded = yaml.safe_load(file)
    except OSError as error:
        raise SettingsValidationError(
            [ValidationIssue("config", f"could not read '{config_path}': {error}")]
        ) from error
    except yaml.YAMLError as error:
        raise SettingsValidationError(
            [ValidationIssue("config", f"contains malformed YAML: {error}")]
        ) from error
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise SettingsValidationError(
            [ValidationIssue("config", "top-level YAML value must be a mapping")]
        )
    return loaded


def _validate_top_level_keys(
    data: Mapping[str, Any], issues: list[ValidationIssue]
) -> None:
    known_fields = tuple(DEFAULTS)
    for key in data:
        if isinstance(key, str) and key in DEFAULTS:
            continue
        field = key if isinstance(key, str) else f"config key {key!r}"
        message = "is not a recognized setting"
        if isinstance(key, str):
            matches = get_close_matches(key, known_fields, n=1, cutoff=0.7)
            if matches:
                message += f"; did you mean '{matches[0]}'?"
        _add_issue(issues, field, message)


def load_settings(
    config_path: str | Path = "config.yaml",
    *,
    create_output_dir: bool = True,
    language_codes_path: str | Path | None = None,
) -> Settings:
    """Load and validate a YAML file, returning one immutable settings object.

    Relative paths in the YAML file are resolved from the YAML file's parent
    directory.  A blank output path selects ``outputs`` beside the YAML file.
    When ``create_output_dir`` is true, that directory (including a custom
    directory) is created only after every field passes validation.
    """

    source_path = Path(config_path).expanduser().resolve(strict=False)
    data = _load_yaml(source_path)
    base_directory = source_path.parent
    application_directory = Path(__file__).resolve().parent
    catalog_path = (
        Path(language_codes_path).expanduser().resolve(strict=False)
        if language_codes_path is not None
        else application_directory / "assets" / "translation_codes" / "translation_codes.yaml"
    )
    issues: list[ValidationIssue] = []
    _validate_top_level_keys(data, issues)

    output_path = _parse_output_path(data, base_directory, issues)
    background_image = _parse_optional_file(data, "background image", base_directory, issues)
    resolution = _parse_resolution(data, background_image, issues)
    background_color = _parse_color(data, "background color", issues)
    quran_font = _parse_font(data, "quran font", base_directory, issues)
    quran_color = _parse_color(data, "quran color", issues)
    quran_font_size = _parse_int(data, "quran font size", issues, minimum=1)
    quran_x_position = _parse_position(data, "quran x position", issues)
    quran_max_width = _parse_int(data, "quran maximum width", issues, minimum=1)
    quran_line_spacing = _parse_int(data, "quran line spacing", issues, minimum=0)
    quran_word_spacing = _parse_int(data, "quran word spacing", issues, minimum=0)
    quran_letter_spacing = _parse_float(data, "quran letter spacing", issues)
    quran_translation_spacing = _parse_int(
        data, "quran and translation spacing", issues, minimum=0
    )
    translation_font_size = _parse_int(
        data, "translation font size", issues, minimum=1
    )
    translations = _parse_translations(
        data,
        base_directory,
        application_directory,
        translation_font_size,
        catalog_path,
        issues,
    )
    translation_color = _parse_color(data, "translation color", issues)
    translation_x_position = _parse_position(data, "translation x position", issues)
    translation_max_width = _parse_int(
        data, "translation maximum width", issues, minimum=1
    )
    translation_language_spacing = _parse_int(
        data, "translation language spacing", issues, minimum=0
    )
    translation_line_spacing = _parse_int(
        data, "translation line spacing", issues, minimum=0
    )
    translation_word_spacing = _parse_int(
        data, "translation word spacing", issues, minimum=0
    )
    translation_letter_spacing = _parse_float(
        data, "translation letter spacing", issues
    )
    show_verse_numbers = _parse_bool(data, "show verse numbers", issues)
    verse_number_resolution = _dimensions_from_value(
        _raw_value(data, "verse number resolution"),
        "verse number resolution",
        str(DEFAULTS["verse number resolution"]),
        issues,
    )
    verse_number_x_offset = _parse_int(
        data, "verse number x offset", issues, minimum=-20, maximum=500
    )
    verse_number_y_offset = _parse_int(data, "verse number y offset", issues)
    space_between_verses = _parse_int(
        data, "space between verses", issues, minimum=-10, maximum=200
    )
    generate_random_verses = _parse_bool(data, "generate random verses", issues)
    total_y_offset = _parse_int(data, "total y offset", issues)
    upload = _parse_upload(data, issues)
    username = _parse_text(data, "username", issues)
    password = _parse_text(data, "password", issues)
    post_method = _parse_text(data, "post method", issues)

    if issues:
        raise SettingsValidationError(issues)

    if create_output_dir:
        try:
            output_path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise SettingsValidationError(
                [ValidationIssue("output path", f"could not create '{output_path}': {error}")]
            ) from error

    return Settings(
        source_path=source_path,
        output_path=output_path,
        resolution=resolution,
        background_image=background_image,
        background_color=background_color,
        quran_font=quran_font,
        quran_color=quran_color,
        quran_font_size=quran_font_size,
        quran_x_position=quran_x_position,
        quran_max_width=quran_max_width,
        quran_line_spacing=quran_line_spacing,
        quran_word_spacing=quran_word_spacing,
        quran_letter_spacing=quran_letter_spacing,
        quran_translation_spacing=quran_translation_spacing,
        translations=translations,
        translation_color=translation_color,
        translation_font_size=translation_font_size,
        translation_x_position=translation_x_position,
        translation_max_width=translation_max_width,
        translation_language_spacing=translation_language_spacing,
        translation_line_spacing=translation_line_spacing,
        translation_word_spacing=translation_word_spacing,
        translation_letter_spacing=translation_letter_spacing,
        show_verse_numbers=show_verse_numbers,
        verse_number_resolution=verse_number_resolution,
        verse_number_x_offset=verse_number_x_offset,
        verse_number_y_offset=verse_number_y_offset,
        space_between_verses=space_between_verses,
        generate_random_verses=generate_random_verses,
        total_y_offset=total_y_offset,
        upload=upload,
        username=username,
        password=password,
        post_method=post_method,
    )
