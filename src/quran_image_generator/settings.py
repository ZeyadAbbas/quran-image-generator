"""Typed, explicit configuration loading for the image generator.

The public entry point is :func:`load_settings`.  Importing this module never
reads configuration, inspects images, or creates directories.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from difflib import get_close_matches
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import yaml

from .models import (
    TranslationResource,
    TranslationSelector,
    TranslationSelectorKind,
)
from .resources import PACKAGE_DIRECTORY, asset_path

Position = int | Literal["center"]


SettingValueType = Literal[
    "boolean",
    "color",
    "dimensions",
    "float",
    "font",
    "integer",
    "path",
    "position",
    "translations",
]
SettingPathSemantics = Literal["none", "directory", "optional-file", "font-file"]


@dataclass(frozen=True, slots=True)
class SettingSpec:
    """User-facing contract for one persisted generation setting."""

    key: str
    attribute: str
    label: str
    category: str
    value_type: SettingValueType
    default: Any
    description: str
    effect: str
    format_hint: str
    minimum: int | float | None = None
    maximum: int | float | None = None
    path_semantics: SettingPathSemantics = "none"


SETTING_SPECS: tuple[SettingSpec, ...] = (
    SettingSpec("output path", "output_path", "Output directory", "Passage & Output", "path", "outputs", "Directory used for generated PNG files.", "Changes where saved images are placed; relative paths are resolved beside the config file.", "Folder path", path_semantics="directory"),
    SettingSpec("resolution", "resolution", "Image resolution", "Canvas", "dimensions", "1080 x 1080", "Full-resolution canvas size.", "Sets preview/save dimensions; bg reads the selected background image's dimensions.", "WIDTH x HEIGHT, or bg when a background image is selected", minimum=1),
    SettingSpec("background image", "background_image", "Background image", "Canvas", "path", "", "Optional image drawn behind the text.", "Replaces the solid background while preserving the configured canvas size.", "Image file path, or blank", path_semantics="optional-file"),
    SettingSpec("background color", "background_color", "Background color", "Canvas", "color", "000000", "Solid canvas background color.", "Used when no background image covers the canvas.", "Six-digit hex color, for example #000000"),
    SettingSpec("quran font", "quran_font", "Quran font", "Quran", "font", "Arial", "Font used for Arabic Quran text.", "Changes the Arabic typeface.", "Arial or a .ttf/.otf file path", path_semantics="font-file"),
    SettingSpec("quran color", "quran_color", "Quran color", "Quran", "color", "FFFFFF", "Color of Quran text.", "Changes the Arabic text color.", "Six-digit hex color, for example #FFFFFF"),
    SettingSpec("quran font size", "quran_font_size", "Quran font size", "Quran", "integer", 34, "Quran text size in pixels.", "Larger values make Arabic text and its layout taller/wider.", "Positive whole number", minimum=1),
    SettingSpec("quran x position", "quran_x_position", "Quran horizontal position", "Quran", "position", 30, "Arabic text position measured from the right, or centered.", "Moves each Quran line horizontally.", "center or a non-negative whole number", minimum=0),
    SettingSpec("quran maximum width", "quran_max_width", "Quran maximum width", "Quran", "integer", 700, "Maximum width of an Arabic line.", "Controls Quran line wrapping.", "Positive whole number", minimum=1),
    SettingSpec("quran line spacing", "quran_line_spacing", "Quran line spacing", "Quran", "integer", 30, "Vertical spacing between wrapped Arabic lines.", "Changes the height of multi-line Quran text.", "Non-negative whole number", minimum=0),
    SettingSpec("quran word spacing", "quran_word_spacing", "Quran word spacing", "Quran", "integer", 6, "Extra spacing between Quran words.", "Changes horizontal word separation.", "Non-negative whole number", minimum=0),
    SettingSpec("quran letter spacing", "quran_letter_spacing", "Quran letter spacing", "Quran", "float", -0.1, "Extra spacing between Quran glyphs.", "Tightens or loosens Arabic letter placement.", "Finite decimal number"),
    SettingSpec("quran and translation spacing", "quran_translation_spacing", "Quran-to-translation spacing", "Quran", "integer", 30, "Gap below Quran text before translations.", "Separates the Arabic and translation blocks.", "Non-negative whole number", minimum=0),
    SettingSpec("translation languages", "translations", "Translations", "Translations", "translations", "", "Up to three exact Quran Foundation translation resources.", "Selects which translations are fetched and their order.", "List of exact IDs/slugs/languages; exact resource IDs are recommended", maximum=3),
    SettingSpec("translation color", "translation_color", "Translation color", "Translations", "color", "FFFFFF", "Color of translation text.", "Changes all translation text colors.", "Six-digit hex color, for example #FFFFFF"),
    SettingSpec("translation font size", "translation_font_size", "Translation font size", "Translations", "integer", 16, "Default translation text size in pixels.", "Changes translation wrapping and height unless an entry overrides it.", "Positive whole number", minimum=1),
    SettingSpec("translation x position", "translation_x_position", "Translation horizontal position", "Translations", "position", 40, "Translation position measured from the left, or centered.", "Moves each translation line horizontally.", "center or a non-negative whole number", minimum=0),
    SettingSpec("translation maximum width", "translation_max_width", "Translation maximum width", "Translations", "integer", 650, "Maximum width of a translation line.", "Controls translation line wrapping.", "Positive whole number", minimum=1),
    SettingSpec("translation language spacing", "translation_language_spacing", "Between translations", "Translations", "integer", 10, "Gap between different translation resources.", "Separates multiple translations for the same verse.", "Non-negative whole number", minimum=0),
    SettingSpec("translation line spacing", "translation_line_spacing", "Translation line spacing", "Translations", "integer", 10, "Gap between wrapped lines in one translation.", "Changes the height of multi-line translation text.", "Non-negative whole number", minimum=0),
    SettingSpec("translation word spacing", "translation_word_spacing", "Translation word spacing", "Translations", "integer", 1, "Extra spacing between translation words.", "Changes horizontal word separation.", "Non-negative whole number", minimum=0),
    SettingSpec("translation letter spacing", "translation_letter_spacing", "Translation letter spacing", "Translations", "float", 0.0, "Extra spacing between translation letters.", "Tightens or loosens translation lettering.", "Finite decimal number"),
    SettingSpec("show verse numbers", "show_verse_numbers", "Show verse numbers", "Verse Numbers & Spacing", "boolean", False, "Whether to draw the verse-number medallion.", "Shows or hides the number after each verse.", "true or false"),
    SettingSpec("verse number resolution", "verse_number_resolution", "Verse-number size", "Verse Numbers & Spacing", "dimensions", "55 x 55", "Width and height of verse-number medallions.", "Scales the number images.", "WIDTH x HEIGHT using positive whole numbers", minimum=1),
    SettingSpec("verse number x offset", "verse_number_x_offset", "Verse-number X offset", "Verse Numbers & Spacing", "integer", 10, "Horizontal adjustment for verse numbers.", "Moves each number left or right relative to the Quran line.", "Whole number from -20 to 500", minimum=-20, maximum=500),
    SettingSpec("verse number y offset", "verse_number_y_offset", "Verse-number Y offset", "Verse Numbers & Spacing", "integer", -20, "Vertical adjustment for verse numbers.", "Moves each number up or down relative to the Quran line.", "Whole number"),
    SettingSpec("space between verses", "space_between_verses", "Space between verses", "Verse Numbers & Spacing", "integer", 70, "Vertical gap between consecutive verses.", "Spreads or tightens multi-verse passages.", "Whole number from -10 to 200", minimum=-10, maximum=200),
    SettingSpec("generate random verses", "generate_random_verses", "Generate random verses", "Passage & Output", "boolean", False, "Choose a short random passage instead of the entered range.", "Uses live chapter bounds for a new random request.", "true or false"),
    SettingSpec("total y offset", "total_y_offset", "Overall Y offset", "Canvas", "integer", -10, "Vertical adjustment for the complete text block.", "Moves all Quran, translation, and verse-number content together.", "Whole number"),
)

SETTING_SPEC_BY_KEY: Mapping[str, SettingSpec] = MappingProxyType(
    {spec.key: spec for spec in SETTING_SPECS}
)
DEFAULTS: Mapping[str, Any] = MappingProxyType(
    {spec.key: spec.default for spec in SETTING_SPECS}
)

_LEGACY_PUBLISH_SETTINGS: Mapping[str, str] = MappingProxyType(
    {
        "upload": (
            "publishing is no longer configured in YAML; remove this key and "
            "use --publish {post,story} when publishing is intended"
        ),
        "username": (
            "credentials must not be stored in YAML; remove this key and use "
            "QIG_INSTAGRAM_USERNAME only when publishing"
        ),
        "password": (
            "credentials must not be stored in YAML; remove this key and use "
            "QIG_INSTAGRAM_PASSWORD only when publishing"
        ),
        "post method": (
            "publishing is no longer configured in YAML; remove this key and "
            "choose post or story with --publish"
        ),
        "post_method": (
            "publishing is no longer configured in YAML; remove this key and "
            "choose post or story with --publish"
        ),
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
    selector: TranslationSelector
    font: Path | str | None
    font_size: int
    resource: TranslationResource | None = None
    configured_font: Path | str | None = None

    def __post_init__(self) -> None:
        if self.resource is None and self.configured_font is None and self.font is not None:
            object.__setattr__(self, "configured_font", self.font)

    @property
    def resource_id(self) -> str:
        if self.resource is None:
            raise RuntimeError(
                f"translation {self.selector.label} has not been resolved "
                "against the Quran Foundation catalog"
            )
        return self.resource.resource_id

    def resolve(self, resource: TranslationResource) -> TranslationSettings:
        """Attach an exact catalog identity and choose its bundled font."""

        font = self.font
        if font is None:
            multilingual_directory = asset_path("fonts", "multilingual_fonts")
            for suffix in (".ttf", ".otf"):
                candidate = multilingual_directory / f"{resource.language_code}{suffix}"
                if candidate.is_file():
                    font = candidate.resolve()
                    break
        return replace(self, font=font or "Arial", resource=resource)


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings shared by the CLI, GUI, and renderer."""

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
    resolution_from_background: bool = False


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _raw_value(data: Mapping[str, Any], field: str) -> Any:
    value = data.get(field)
    return DEFAULTS[field] if _is_blank(value) else value


def _add_issue(issues: list[ValidationIssue], field: str, message: str) -> None:
    issues.append(ValidationIssue(field, message))


def _parse_int(
    data: Mapping[str, Any],
    field: str,
    issues: list[ValidationIssue],
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    spec = SETTING_SPEC_BY_KEY[field]
    if minimum is None and spec.minimum is not None:
        minimum = int(spec.minimum)
    if maximum is None and spec.maximum is not None:
        maximum = int(spec.maximum)
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
    if len(text) != 6 or any(
        character not in "0123456789abcdefABCDEF" for character in text
    ):
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
    minimum = int(SETTING_SPEC_BY_KEY[field].minimum or 0)
    if value is None or value < minimum:
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
    application_directory: Path,
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
    if not path.is_file():
        package_relative = (application_directory / text).resolve(strict=False)
        bundled_font = asset_path("fonts", text).resolve(strict=False)
        if package_relative.is_file():
            path = package_relative
        elif bundled_font.is_file():
            path = bundled_font
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
    minimum = int(SETTING_SPEC_BY_KEY[field].minimum or 1)
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

    if len(values) != 2 or any(value < minimum for value in values):
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
            _add_issue(
                issues, field, f"could not read dimensions from {background_image}"
            )
            return Dimensions(1080, 1080)
        return Dimensions(width, height)
    return _dimensions_from_value(raw, field, str(DEFAULTS[field]), issues)


def _translation_entries(
    raw: Any, issues: list[ValidationIssue]
) -> list[tuple[TranslationSelector, Any, Any]]:
    field = "translation languages"
    if _is_blank(raw):
        return []
    if isinstance(raw, str):
        entries: Sequence[Any] = [
            item.strip() for item in raw.split(",") if item.strip()
        ]
    elif isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        entries = raw
    else:
        _add_issue(
            issues,
            field,
            "must be a comma-separated string or a list of language entries",
        )
        return []

    parsed: list[tuple[TranslationSelector, Any, Any]] = []
    for index, entry in enumerate(entries):
        entry_field = f"{field}[{index}]"
        selector_kind: TranslationSelectorKind
        if isinstance(entry, Mapping):
            allowed_fields = {
                "id",
                "slug",
                "language",
                "code",
                "font",
                "font size",
                "font_size",
            }
            unknown_fields = tuple(
                key
                for key in entry
                if not isinstance(key, str) or key not in allowed_fields
            )
            if unknown_fields:
                joined = ", ".join(repr(key) for key in unknown_fields)
                _add_issue(
                    issues,
                    entry_field,
                    f"contains unrecognized field(s): {joined}",
                )

            selectors: list[tuple[TranslationSelectorKind, Any]] = []
            for kind in ("id", "slug", "language"):
                if kind in entry and not _is_blank(entry[kind]):
                    selectors.append((kind, entry[kind]))
            if "code" in entry and not _is_blank(entry["code"]):
                selectors.append(("language", entry["code"]))
            if len(selectors) != 1:
                _add_issue(
                    issues,
                    entry_field,
                    "must contain exactly one selector: id, slug, or language",
                )
                continue
            selector_kind, selector_value = selectors[0]
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
            selector_kind = "language"
            selector_value = parts[0]
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

        if (
            selector_kind == "id"
            and isinstance(selector_value, int)
            and not isinstance(selector_value, bool)
        ):
            selector_text = str(selector_value)
        elif isinstance(selector_value, str):
            selector_text = selector_value
        else:
            _add_issue(
                issues,
                entry_field,
                f"{selector_kind} selector must be text"
                if selector_kind != "id"
                else "id selector must be a positive whole number",
            )
            continue
        try:
            selector = TranslationSelector(selector_kind, selector_text)
        except ValueError as error:
            _add_issue(issues, entry_field, str(error))
            continue
        parsed.append((selector, font, font_size))
    return parsed


def _translation_font(
    raw: Any,
    base_directory: Path,
    application_directory: Path,
    field: str,
    issues: list[ValidationIssue],
) -> Path | str | None:
    if _is_blank(raw):
        return None
    if not isinstance(raw, (str, Path)):
        _add_issue(issues, field, "font must be 'Arial' or a .ttf/.otf file path")
        return "Arial"
    text = str(raw).strip()
    if text.lower() == "arial":
        return "Arial"
    path = _resolve_path(text, base_directory)
    if not path.is_file():
        package_relative = (application_directory / text).resolve(strict=False)
        bundled_font = asset_path("fonts", text).resolve(strict=False)
        if package_relative.is_file():
            path = package_relative
        elif bundled_font.is_file():
            path = bundled_font
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
    issues: list[ValidationIssue],
) -> tuple[TranslationSettings, ...]:
    field = "translation languages"
    entries = _translation_entries(data.get(field), issues)
    if not entries:
        return ()
    maximum = int(SETTING_SPEC_BY_KEY[field].maximum or 3)
    if len(entries) > maximum:
        _add_issue(issues, field, f"supports at most {maximum} languages")
        entries = entries[:maximum]
    translations: list[TranslationSettings] = []
    seen_selectors: set[tuple[str, str]] = set()
    for index, (selector, raw_font, raw_font_size) in enumerate(entries):
        entry_field = f"{field}[{index}]"
        selector_identity = (selector.kind, selector.value.casefold())
        if selector_identity in seen_selectors:
            _add_issue(issues, entry_field, f"duplicates selector '{selector.label}'")
            continue
        seen_selectors.add(selector_identity)
        font = _translation_font(
            raw_font,
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
                _add_issue(
                    issues,
                    f"{entry_field}.font size",
                    "must be a positive whole number",
                )
            else:
                font_size = parsed_font_size
        translations.append(
            TranslationSettings(
                selector,
                font,
                font_size,
                configured_font=font,
            )
        )
    return tuple(translations)


def _load_yaml(config_path: Path) -> Mapping[str, Any]:
    malformed = False
    try:
        with config_path.open("r", encoding="utf-8") as file:
            loaded = yaml.safe_load(file)
    except OSError as error:
        raise SettingsValidationError(
            [ValidationIssue("config", f"could not read '{config_path}': {error}")]
        ) from error
    except yaml.YAMLError:
        malformed = True
        loaded = None
    if malformed:
        raise SettingsValidationError(
            [ValidationIssue("config", "contains malformed YAML")]
        )
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
        if isinstance(key, str) and key in _LEGACY_PUBLISH_SETTINGS:
            _add_issue(issues, key, _LEGACY_PUBLISH_SETTINGS[key])
            continue
        field = key if isinstance(key, str) else f"config key {key!r}"
        message = "is not a recognized setting"
        if isinstance(key, str):
            matches = get_close_matches(key, known_fields, n=1, cutoff=0.7)
            if matches:
                message += f"; did you mean '{matches[0]}'?"
        _add_issue(issues, field, message)


def settings_from_mapping(
    data: Mapping[str, Any],
    *,
    source_path: str | Path = "config.yaml",
    create_output_dir: bool = False,
) -> Settings:
    """Validate public config values without requiring a YAML file.

    Relative paths are resolved from ``source_path``'s parent directory.  A
    blank output path selects ``outputs`` beside that logical config file.
    When ``create_output_dir`` is true, that directory (including a custom
    directory) is created only after every field passes validation.
    """

    resolved_source_path = Path(source_path).expanduser().resolve(strict=False)
    base_directory = resolved_source_path.parent
    application_directory = PACKAGE_DIRECTORY
    issues: list[ValidationIssue] = []
    _validate_top_level_keys(data, issues)

    output_path = _parse_output_path(data, base_directory, issues)
    background_image = _parse_optional_file(
        data, "background image", base_directory, issues
    )
    resolution_from_background = (
        isinstance(_raw_value(data, "resolution"), str)
        and str(_raw_value(data, "resolution")).strip().lower() == "bg"
    )
    resolution = _parse_resolution(data, background_image, issues)
    background_color = _parse_color(data, "background color", issues)
    quran_font = _parse_font(
        data,
        "quran font",
        base_directory,
        application_directory,
        issues,
    )
    quran_color = _parse_color(data, "quran color", issues)
    quran_font_size = _parse_int(data, "quran font size", issues)
    quran_x_position = _parse_position(data, "quran x position", issues)
    quran_max_width = _parse_int(data, "quran maximum width", issues)
    quran_line_spacing = _parse_int(data, "quran line spacing", issues)
    quran_word_spacing = _parse_int(data, "quran word spacing", issues)
    quran_letter_spacing = _parse_float(data, "quran letter spacing", issues)
    quran_translation_spacing = _parse_int(
        data, "quran and translation spacing", issues
    )
    translation_font_size = _parse_int(data, "translation font size", issues)
    translations = _parse_translations(
        data,
        base_directory,
        application_directory,
        translation_font_size,
        issues,
    )
    translation_color = _parse_color(data, "translation color", issues)
    translation_x_position = _parse_position(data, "translation x position", issues)
    translation_max_width = _parse_int(
        data, "translation maximum width", issues
    )
    translation_language_spacing = _parse_int(
        data, "translation language spacing", issues
    )
    translation_line_spacing = _parse_int(
        data, "translation line spacing", issues
    )
    translation_word_spacing = _parse_int(
        data, "translation word spacing", issues
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
        data, "verse number x offset", issues
    )
    verse_number_y_offset = _parse_int(data, "verse number y offset", issues)
    space_between_verses = _parse_int(
        data, "space between verses", issues
    )
    generate_random_verses = _parse_bool(data, "generate random verses", issues)
    total_y_offset = _parse_int(data, "total y offset", issues)

    if issues:
        raise SettingsValidationError(issues)

    if create_output_dir:
        try:
            output_path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise SettingsValidationError(
                [
                    ValidationIssue(
                        "output path", f"could not create '{output_path}': {error}"
                    )
                ]
            ) from error

    return Settings(
        source_path=resolved_source_path,
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
        resolution_from_background=resolution_from_background,
    )


def load_settings(
    config_path: str | Path = "config.yaml",
    *,
    create_output_dir: bool = True,
) -> Settings:
    """Load and validate a YAML file, returning one immutable settings object."""

    source_path = Path(config_path).expanduser().resolve(strict=False)
    return settings_from_mapping(
        _load_yaml(source_path),
        source_path=source_path,
        create_output_dir=create_output_dir,
    )


def _portable_path(value: Path | str, destination_path: Path) -> str:
    if isinstance(value, str):
        return value
    resolved = value.resolve(strict=False)
    try:
        return resolved.relative_to(PACKAGE_DIRECTORY.resolve()).as_posix()
    except ValueError:
        pass
    try:
        return Path(os.path.relpath(resolved, destination_path.parent)).as_posix()
    except ValueError:  # Different Windows drives cannot be made relative.
        return str(resolved)


def _translation_mapping(
    settings: Settings, destination_path: Path
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for translation in settings.translations:
        selector_value: str | int = translation.selector.value
        if translation.selector.kind == "id":
            selector_value = int(selector_value)
        entry: dict[str, Any] = {translation.selector.kind: selector_value}
        configured_font = (
            translation.configured_font
            if translation.resource is not None
            else translation.font
        )
        if configured_font is not None:
            entry["font"] = _portable_path(configured_font, destination_path)
        if translation.font_size != settings.translation_font_size:
            entry["font size"] = translation.font_size
        entries.append(entry)
    return entries


def settings_to_mapping(
    settings: Settings,
    *,
    destination_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return only the validated, public YAML fields for ``settings``.

    Runtime catalog objects and auto-resolved bundled translation fonts are
    deliberately excluded.  Paths are made relative to the destination where
    possible, and package assets use stable package-relative names.
    """

    destination = (
        settings.source_path
        if destination_path is None
        else Path(destination_path).expanduser().resolve(strict=False)
    )
    data: dict[str, Any] = {}
    for spec in SETTING_SPECS:
        value = getattr(settings, spec.attribute)
        if spec.value_type == "translations":
            value = _translation_mapping(settings, destination)
        elif spec.value_type == "dimensions":
            value = (
                "bg"
                if spec.key == "resolution" and settings.resolution_from_background
                else f"{value.width} x {value.height}"
            )
        elif spec.path_semantics == "optional-file":
            value = "" if value is None else _portable_path(value, destination)
        elif spec.path_semantics in {"directory", "font-file"}:
            value = _portable_path(value, destination)
        data[spec.key] = value
    return data


def save_settings(settings: Settings, config_path: str | Path) -> Settings:
    """Validate and atomically save settings, returning their saved form."""

    destination = Path(config_path).expanduser().resolve(strict=False)
    data = settings_to_mapping(settings, destination_path=destination)
    normalized = settings_from_mapping(
        data,
        source_path=destination,
        create_output_dir=False,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            yaml.safe_dump(
                data,
                temporary_file,
                sort_keys=False,
                allow_unicode=True,
            )
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return normalized


def settings_help_text() -> str:
    """Build concise GUI/documentation help from the authoritative schema."""

    sections: list[str] = []
    for spec in SETTING_SPECS:
        default = spec.default if spec.default != "" else "blank"
        sections.append(
            f"{spec.label} ({spec.key})\n"
            f"  {spec.description} {spec.effect}\n"
            f"  Format: {spec.format_hint}. Default: {default}."
        )
    return "\n\n".join(sections)


# Short public spellings are convenient for non-file front ends.
from_mapping = settings_from_mapping
to_mapping = settings_to_mapping
