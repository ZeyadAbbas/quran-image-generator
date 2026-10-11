"""Development examples for measured reference requests; no app preset is installed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont

from quran_image_generator.content import QuranDataClient
from quran_image_generator.profiles import CaptionProfile
from quran_image_generator.references import ReferenceError
from quran_image_generator.scenes import Scene, checked_asset


def creator_profile(scene: Scene) -> CaptionProfile:
    """Historical bundled-font test recipe, separate from renderer defaults."""
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
        "reference-example",
        "1-preview",
        "needs_review",
        styles,
        {
            "assets": assets,
            "reference_geometry": "observed, not approved",
            "word_highlighting": False,
        },
    )


ALI_SHA256 = "57c70bf2efe34444a54ab065173c3d0152e7dd4dc320926fc34e24c85e82d3cd"
SURAH_SHA256 = "8c989d70fcd8b94829f3fe3338d88f71e764840499494b4d41aa2ebd78fbc027"
ME_QURAN_SHA256 = "65464072d7c754baa642a4f5031d6cb3b6311cf06ad1826f8fd317f98283096d"


def matched_creator_titles(surah: int) -> dict[str, str]:
    """Explicit title overrides preserving spellings visible in the six references."""
    chapter = QuranDataClient().get_chapter(surah)
    aliases = {
        2: "Al-Baqarah",
        5: "Al-Ma'idah",
        17: "Al-Isra",
        31: "Luqman",
        39: "Az-Zumar",
    }
    return {
        "arabic_title": f"سورة {chapter.name_arabic}",
        "latin_title": f"Surah {aliases.get(surah, chapter.name_simple)}",
    }


def _find_font(directory: Path, digest: str) -> Path:
    for path in sorted(directory.rglob("*.ttf")):
        if checked_asset(str(path)) == digest:
            return path.resolve()
    raise ReferenceError(
        "missing_font",
        "The supplied creator folder lacks the pinned font; restore the original file",
    )


def matched_creator_configuration(directory: Path, latin_font: Path) -> dict[str, Any]:
    """Request options for the original me_quran/ALI/Arial/surah-logo profile.

    Caller supplies the fonts under their own terms. No font binaries are copied.
    Arial is selected explicitly, never found through silent system fallback.
    """
    decorations = _find_font(directory, ALI_SHA256)
    arabic = _find_font(directory, ME_QURAN_SHA256)
    logo = _find_font(directory, SURAH_SHA256)
    latin_digest = checked_asset(str(latin_font))
    with TTFont(latin_font) as font:
        if (font["name"].getDebugName(1), font["name"].getDebugName(2)) != (
            "Arial",
            "Regular",
        ):
            raise ReferenceError("invalid_font", "Supply Arial Regular explicitly")
    assets = {
        "arabic": {
            "path": str(arabic),
            "sha256": ME_QURAN_SHA256,
            "license": "Creator-supplied me_quran file; not redistributed by this helper",
            "attribution": "me_quran; identical to the bundled Quran font",
        },
        "decorations": {
            "path": str(decorations),
            "sha256": ALI_SHA256,
            "license": "Freeware, per supplied info.txt; retain original terms",
            "attribution": "AL-QURAN-ALI / Ali Laith Kaser Ali; creator-supplied file",
        },
        "logo": {
            "path": str(logo),
            "sha256": SURAH_SHA256,
            "glyph": "y",
            "license": "Public Domain, per supplied info.txt",
            "attribution": "Quran Surah 01 / elharrak fonts; creator-supplied file",
        },
    }
    assets["arabic_title"] = dict(assets["arabic"])
    for role in ("latin_title", "translation"):
        assets[role] = {
            "path": str(latin_font.resolve()),
            "sha256": latin_digest,
            "license": "Caller-owned system font; not redistributed",
            "attribution": "Explicit caller-selected Arial Regular",
        }
    shared = {
        "color": "#FFFFFF",
        "outline_width": 0,
        "shadow_offset": (0, 0),
        "shadow_blur": 0,
        "shadow_opacity": 0,
    }
    styles = {
        "arabic": {
            **shared,
            "font_size": 25.25,
            "horizontal_scale": 1.14,
            "decoration_scale": 1.14,
            "min_font_size": 24,
            "anchor": (0.5, 0.503),
            "region": (0.025, 0.28, 0.975, 0.53),
            "quote_open": "{",
            "quote_close": "}",
            "numeral_system": "latin",
            "marker_prefix": "(",
            "marker_suffix": ")",
            "suffix_scale": 0.435,
            "suffix_offset": -4,
            "suffix_spacing": 5,
            "fit": "shrink",
            "max_lines": 4,
        },
        "arabic_title": {
            **shared,
            "font_size": 23.5,
            "horizontal_scale": 1.08,
            "min_font_size": 20,
            "anchor": (0.5, 0.161),
            "region": (0.05, 0.12, 0.95, 0.173),
        },
        "latin_title": {
            **shared,
            "font_size": 14.5,
            "min_font_size": 12,
            "anchor": (0.5, 0.1865),
            "region": (0.05, 0.17, 0.95, 0.205),
        },
        "translation": {
            **shared,
            "font_size": 14.5,
            "min_font_size": 12,
            "anchor": (0.5, 0.542),
            "region": (0.12, 0.525, 0.88, 0.68),
            "line_spacing": 2,
            "max_lines": 3,
        },
        "logo": {
            **shared,
            "font_size": 59.25,
            "anchor": (0.5, 0.9253),
            "region": (0.4, 0.86, 0.6, 0.97),
        },
    }
    for role, asset in assets.items():
        if role != "decorations":
            styles[role]["sha256"] = asset["sha256"]
    profile = CaptionProfile(
        "reference-example",
        "2-matched",
        "needs_review",
        styles,
        {
            "assets": assets,
            "reference_sources": [
                "7339743928691821854",
                "7320492468246416670",
                "7320203938483981599",
                "7320147035552779550",
                "7320128271927020831",
                "7295439449779965214",
            ],
            "logo_glyph": {
                "character": "y",
                "codepoint": "U+0079",
                "font_sha256": SURAH_SHA256,
            },
            "arabic_font": "me_quran",
            "decoration_font": "AL-QURAN-ALI",
            "latin_font": "Arial Regular candidate",
            "word_highlighting": False,
            "reference_geometry": "measured local source frames; visual review pending",
        },
    )
    return {
        "assets": assets,
        "profile": profile.to_dict(),
        "titles": True,
        "quotations": True,
        "verse_numbers": True,
    }
