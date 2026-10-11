"""Caller-defined layer styles with explicit revision and review provenance."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import jsonschema

from .contract_schema import PROFILE
from .excerpts import Excerpt
from .references import ReferenceError
from .scenes import Scene


@dataclass(frozen=True, slots=True)
class CaptionProfile:
    id: str
    revision: str
    approval: str
    styles: dict[str, dict[str, Any]]
    provenance: dict[str, Any]

    def validate(self) -> None:
        try:
            jsonschema.Draft202012Validator(PROFILE).validate(
                json.loads(json.dumps(asdict(self), allow_nan=False))
            )
        except (jsonschema.ValidationError, TypeError, ValueError) as error:
            raise ReferenceError(
                "invalid_profile",
                "Profile does not conform to the layer style contract",
            ) from error
        if set(self.styles) - {
            "arabic",
            "translation",
            "arabic_title",
            "latin_title",
            "logo",
        }:
            raise ReferenceError("invalid_profile", "Unknown profile layer role")

    def apply(self, scene: Scene) -> Scene:
        self.validate()
        try:
            return replace(
                scene,
                layers=tuple(
                    replace(layer, **self.styles.get(layer.role, {}))
                    for layer in scene.layers
                ),
            )
        except TypeError as error:
            raise ReferenceError(
                "invalid_profile", "Unknown profile layer field"
            ) from error

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaptionProfile:
        try:
            result = cls(**data)
            result.validate()
            return result
        except TypeError as error:
            raise ReferenceError(
                "invalid_profile", "Malformed profile object"
            ) from error


def decorate_excerpt(
    excerpt: Excerpt,
    scene: Scene,
    *,
    quotations: bool = True,
    verse_numbers: bool = True,
) -> Scene:
    arabic = next(layer for layer in scene.layers if layer.role == "arabic")
    digits = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")

    def marker(ayah: int) -> str:
        number = str(ayah)
        if arabic.numeral_system == "arabic_indic":
            number = number.translate(digits)
        return arabic.marker_prefix + number + arabic.marker_suffix

    # Multiple ayah endings stay with their individual source spans.
    if len(excerpt.spans) > 1 and verse_numbers:
        text = " ".join(
            span.text
            + (
                f" {marker(span.source.ayah)}"
                if span.ends_ayah and span.source.surah
                else ""
            )
            for span in excerpt.spans
        )
        suffix = ""
    else:
        text = excerpt.text
        suffix = (
            marker(excerpt.spans[-1].source.ayah)
            if verse_numbers and excerpt.verse_markers
            else ""
        )
    separate = bool(arabic.decoration_font)
    display = (
        f"{arabic.quote_open} {text} {arabic.quote_close}"
        if quotations and not separate
        else text
    )
    return replace(
        scene,
        layers=tuple(
            replace(
                layer,
                text=display,
                suffix=suffix,
                ornaments=quotations and separate,
                inline_markers=tuple(
                    marker(s.source.ayah)
                    for s in excerpt.spans
                    if s.ends_ayah and s.source.surah
                )
                if separate and len(excerpt.spans) > 1 and verse_numbers
                else (),
            )
            if layer.role == "arabic"
            else layer
            for layer in scene.layers
        ),
    )


def export_profile(profile: CaptionProfile, path: Path) -> None:
    path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), "utf-8"
    )


def import_profile(path: Path) -> CaptionProfile:
    if path.stat().st_size > 1_000_000:
        raise ReferenceError("invalid_profile", "Profile exceeds 1 MB")
    try:
        data = json.loads(path.read_text("utf-8-sig"))
        profile = CaptionProfile.from_dict(data)
        for style in profile.styles.values():
            for name in ("anchor", "region", "shadow_offset"):
                if name in style:
                    style[name] = tuple(style[name])
        return profile
    except (KeyError, TypeError, ValueError) as error:
        raise ReferenceError("invalid_profile", "Malformed profile JSON") from error
