"""Versioned scene profiles; creator asset approval is explicit provenance."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .excerpts import Excerpt
from .references import ReferenceError
from .scenes import Scene, checked_asset


@dataclass(frozen=True, slots=True)
class CaptionProfile:
    id: str
    revision: str
    approval: str
    styles: dict[str, dict[str, Any]]
    provenance: dict[str, Any]

    def apply(self, scene: Scene) -> Scene:
        if (
            self.approval not in ("approved", "needs_review")
            or not self.id
            or not self.revision
        ):
            raise ReferenceError(
                "invalid_profile", "Profile identity and approval state are required"
            )
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
        return asdict(self)


def creator_profile(scene: Scene) -> CaptionProfile:
    """Observed starting geometry with bundled assets, explicitly unapproved."""
    styles = {}
    assets = {}
    for layer in scene.layers:
        styles[layer.role] = {
            "color": "#FFFFFF",
            "outline_width": 1,
            "shadow_offset": (0, 1),
            "shadow_blur": 1,
            "shadow_opacity": 0.5,
        }
        if layer.font or layer.image:
            digest = checked_asset(layer.image or layer.font, layer.sha256)
            styles[layer.role]["sha256"] = digest
            assets[layer.role] = {
                "sha256": digest,
                "source": "caller-supplied" if layer.image else "bundled fallback",
                "approval": "needs_review",
            }
    return CaptionProfile(
        "islamstruebeauty",
        "1-preview",
        "needs_review",
        styles,
        {
            "assets": assets,
            "reference_geometry": "observed, not approved",
            "word_highlighting": False,
        },
    )


def decorate_excerpt(
    excerpt: Excerpt,
    scene: Scene,
    *,
    quotations: bool = True,
    verse_numbers: bool = True,
) -> Scene:
    digits = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
    # Multiple ayah endings stay with their individual source spans.
    if len(excerpt.spans) > 1 and verse_numbers:
        text = " ".join(
            span.text
            + (
                f" {str(span.source.ayah).translate(digits)}"
                if span.ends_ayah and span.source.surah
                else ""
            )
            for span in excerpt.spans
        )
        suffix = ""
    else:
        text = excerpt.text
        suffix = (
            str(excerpt.spans[-1].source.ayah).translate(digits)
            if verse_numbers and excerpt.verse_markers
            else ""
        )
    display = f"﴿ {text} ﴾" if quotations else text
    return replace(
        scene,
        layers=tuple(
            replace(layer, text=display, suffix=suffix)
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
        for style in data["styles"].values():
            for name in ("anchor", "region", "shadow_offset"):
                if name in style:
                    style[name] = tuple(style[name])
        return CaptionProfile(**data)
    except (KeyError, TypeError, ValueError) as error:
        raise ReferenceError("invalid_profile", "Malformed profile JSON") from error
