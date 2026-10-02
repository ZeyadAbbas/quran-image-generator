"""Independent scene layers with RAQM shaping and reusable persistent assets."""

from __future__ import annotations

import hashlib
import math
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageColor, ImageFilter

from .asset_records import OverlayAsset
from .content import QuranDataClient
from .excerpts import Excerpt
from .references import ReferenceError
from .resources import asset_path
from .shaping import ShapedFont


@dataclass(frozen=True, slots=True)
class Layer:
    role: str
    text: str = ""
    font: str = ""
    image: str = ""
    font_size: int = 30
    anchor: tuple[float, float] = (0.5, 0.5)
    region: tuple[float, float, float, float] = (0.05, 0.05, 0.95, 0.95)
    direction: str = "rtl"
    color: str = "#FFFFFF"
    opacity: float = 1
    z_order: int = 0
    enabled: bool = True
    required: bool = True
    persistent: bool = False
    sha256: str = ""
    outline_width: float = 0
    outline_color: str = "#000000"
    shadow_offset: tuple[float, float] = (0, 0)
    shadow_blur: float = 0
    shadow_color: str = "#000000"
    shadow_opacity: float = 0
    suffix: str = ""
    suffix_scale: float = 0.55
    min_font_size: int = 12
    max_lines: int = 3
    line_spacing: float = 8
    baseline_anchor: str = "last"
    fit: str = "wrap"
    alignment: str = "center"
    safe_margin: float = 0


@dataclass(frozen=True, slots=True)
class Scene:
    width: int
    height: int
    layers: tuple[Layer, ...]

    def validate(self) -> None:
        if (
            any(
                type(v) is not int or not 16 <= v <= 4096
                for v in (self.width, self.height)
            )
            or self.width * self.height > 8_500_000
        ):
            raise ReferenceError(
                "invalid_request",
                "Canvas must be 16..4096 pixels with at most 8.5 million pixels",
            )
        if len(self.layers) > 16 or len({item.role for item in self.layers}) != len(
            self.layers
        ):
            raise ReferenceError(
                "invalid_request", "Layer roles must be unique, at most 16"
            )
        for layer in self.layers:
            if (
                layer.fit not in ("wrap", "shrink")
                or layer.baseline_anchor not in ("first", "last")
                or layer.alignment not in ("left", "center", "right")
                or not 1 <= layer.min_font_size <= layer.font_size
                or not 1 <= layer.max_lines <= 8
                or not 0 <= layer.line_spacing <= 64
                or not 0 <= layer.safe_margin <= 64
            ):
                raise ReferenceError(
                    "invalid_request",
                    "Invalid fit, readable font bounds or line constraints",
                )
            if (
                not layer.role
                or not 0 <= layer.opacity <= 1
                or layer.direction not in ("rtl", "ltr")
            ):
                raise ReferenceError(
                    "invalid_request", "Invalid layer role/opacity/direction"
                )
            if not 1 <= layer.font_size <= 256 or len(layer.text) > 8000:
                raise ReferenceError(
                    "invalid_request", "Invalid font size or oversized layer text"
                )
            if (
                not 0 <= layer.outline_width <= 8
                or not 0 <= layer.shadow_blur <= 16
                or not 0 <= layer.shadow_opacity <= 1
                or not 0.25 <= layer.suffix_scale <= 1
                or any(abs(v) > 32 for v in layer.shadow_offset)
            ):
                raise ReferenceError(
                    "invalid_request", "Invalid outline, shadow or marker style"
                )
            for color in (layer.color, layer.outline_color, layer.shadow_color):
                try:
                    if len(ImageColor.getrgb(color)) != 3:
                        raise ValueError("Use opaque RGB colors and separate opacity")
                except ValueError as error:
                    raise ReferenceError(
                        "invalid_request", "Use valid RGB colors"
                    ) from error
            if (
                any(
                    not math.isfinite(v) or not 0 <= v <= 1
                    for v in (*layer.anchor, *layer.region)
                )
                or layer.region[0] >= layer.region[2]
                or layer.region[1] >= layer.region[3]
            ):
                raise ReferenceError(
                    "invalid_request",
                    "Anchors and regions use normalized 0..1 coordinates",
                )
            if layer.enabled and layer.required and not layer.text and not layer.image:
                raise ReferenceError(
                    "missing_asset", f"Required {layer.role} content is missing"
                )


@dataclass(frozen=True, slots=True)
class LayerPlan:
    layer: Layer
    lines: tuple[tuple[str, float, float], ...]
    bounds: tuple[int, int, int, int] | None
    font_size: int
    asset_sha256: str
    status: str = "ready"
    suffix_position: tuple[float, float, int] | None = None


def checked_asset(path: str, expected_hash: str = "") -> str:
    selected = Path(path)
    if not path or not selected.is_file():
        raise ReferenceError(
            "missing_asset", "Required local font/image asset is missing"
        )
    if selected.stat().st_size > 32_000_000:
        raise ReferenceError("invalid_asset", "Asset exceeds 32 MB")
    digest = hashlib.sha256(selected.read_bytes()).hexdigest()
    if expected_hash and digest != expected_hash:
        raise ReferenceError("changed_asset", "Asset content hash changed")
    return digest


def layer_font(layer: Layer, size: int) -> ShapedFont:
    try:
        return ShapedFont(layer.font, size, layer.direction)
    except OSError as error:
        raise ReferenceError(
            "missing_font", "Required font could not be loaded"
        ) from error


def check_glyphs(layer: Layer) -> None:
    try:
        with TTFont(layer.font) as font:
            cmap = font.getBestCmap() or {}
            missing = sorted(
                {
                    ord(c)
                    for c in layer.text + layer.suffix
                    if not c.isspace()
                    and unicodedata.category(c) != "Cf"
                    and (ord(c) not in cmap or cmap[ord(c)] == ".notdef")
                }
            )
    except (OSError, ValueError) as error:
        raise ReferenceError("missing_font", "Required font is invalid") from error
    if missing:
        raise ReferenceError(
            "missing_glyph",
            f"{layer.role} font lacks glyphs: "
            + ", ".join(f"U+{c:04X}" for c in missing[:20]),
        )


def plan_scene(scene: Scene) -> tuple[LayerPlan, ...]:
    scene.validate()
    plans = []
    for layer in sorted(scene.layers, key=lambda item: item.z_order):
        if not layer.enabled or not layer.text and not layer.image:
            plans.append(
                LayerPlan(
                    layer,
                    (),
                    None,
                    0,
                    "",
                    "disabled" if not layer.enabled else "omitted_optional",
                )
            )
            continue
        digest = checked_asset(layer.image or layer.font, layer.sha256)
        if layer.image:
            from .caption_fit import FitError, pixel_region, within

            allowed = pixel_region(scene, layer)
            with Image.open(layer.image) as logo:
                max_w = allowed[2] - allowed[0]
                max_h = allowed[3] - allowed[1]
                scale = min(max_w / logo.width, max_h / logo.height)
                w, h = (
                    max(1, math.floor(logo.width * scale)),
                    max(1, math.floor(logo.height * scale)),
                )
            image_x, image_y = (
                round(layer.anchor[0] * scene.width - w / 2),
                round(layer.anchor[1] * scene.height - h / 2),
            )
            image_bounds = (image_x, image_y, image_x + w, image_y + h)
            if not within(image_bounds, pixel_region(scene, layer)):
                raise FitError(
                    layer.role, image_bounds, pixel_region(scene, layer), 0, 0
                )
            plans.append(LayerPlan(layer, (), image_bounds, 0, digest))
            continue
        from .caption_fit import plan_text

        plans.append(plan_text(scene, layer, digest))
    return tuple(plans)


def render_layer(
    scene: Scene, plan: LayerPlan, destination: Path, *, cropped: bool = False
) -> OverlayAsset:
    with Image.new("RGBA", (scene.width, scene.height), (0, 0, 0, 0)) as image:
        layer = plan.layer
        if plan.status == "ready":
            checked_asset(layer.image or layer.font, plan.asset_sha256)
            if layer.image and plan.bounds:
                left, top, right, bottom = plan.bounds
                with Image.open(layer.image) as original:
                    with original.convert("RGBA") as rgba:
                        with rgba.resize(
                            (right - left, bottom - top), Image.Resampling.LANCZOS
                        ) as logo:
                            image.alpha_composite(logo, (left, top))
            else:
                font = layer_font(layer, plan.font_size)
                with Image.new("RGBA", image.size, (0, 0, 0, 0)) as glyphs:
                    for text, x, y in plan.lines:
                        font.paint(glyphs, text, x, y, "#FFFFFF")
                    if plan.suffix_position:
                        sx, sy, ss = plan.suffix_position
                        layer_font(layer, ss).paint(
                            glyphs, layer.suffix, sx, sy, "#FFFFFF"
                        )
                    with glyphs.getchannel("A") as mask:
                        scale = scene.width / 576
                        if layer.shadow_opacity:
                            with (
                                mask.filter(
                                    ImageFilter.GaussianBlur(layer.shadow_blur * scale)
                                ) as blur,
                                Image.new("L", image.size, 0) as moved,
                            ):
                                moved.paste(
                                    blur,
                                    (
                                        round(layer.shadow_offset[0] * scale),
                                        round(layer.shadow_offset[1] * scale),
                                    ),
                                )
                                _color_mask(
                                    image,
                                    moved,
                                    layer.shadow_color,
                                    layer.shadow_opacity,
                                )
                        stroke = round(layer.outline_width * scale)
                        if stroke:
                            with mask.filter(
                                ImageFilter.MaxFilter(2 * stroke + 1)
                            ) as outline:
                                _color_mask(image, outline, layer.outline_color, 1)
                        _color_mask(image, mask, layer.color, 1)
            if layer.opacity != 1:
                with image.getchannel("A") as alpha:
                    image.putalpha(alpha.point(lambda a: round(a * layer.opacity)))
        with image.getchannel("A") as alpha:
            bounds = alpha.getbbox()
        offset = (0, 0)
        if cropped and bounds:
            offset = (bounds[0], bounds[1])
            with image.crop(bounds) as crop:
                crop.save(destination, "PNG")
                width, height = crop.size
        else:
            image.save(destination, "PNG")
            width, height = image.size
        return OverlayAsset(
            hashlib.sha256(destination.read_bytes()).hexdigest(),
            width,
            height,
            offset,
            bounds,
        )


def _color_mask(
    image: Image.Image, mask: Image.Image, color: str, opacity: float
) -> None:
    with Image.new("RGBA", image.size, ImageColor.getrgb(color) + (255,)) as colored:
        colored.putalpha(mask.point(lambda a: round(a * opacity)))
        image.alpha_composite(colored)


def caption_scene(
    excerpt: Excerpt,
    *,
    width: int = 576,
    height: int = 1024,
    english: str = "",
    titles: bool = False,
    logo: str = "",
    arabic_title: str = "",
    latin_title: str = "",
    title_surah: int | None = None,
) -> Scene:
    arabic_font = str(asset_path("fonts", "quran_font.ttf"))
    latin_font = str(asset_path("fonts", "multilingual_fonts", "am.ttf"))
    layers = [
        Layer(
            "arabic",
            excerpt.text,
            arabic_font,
            font_size=30,
            anchor=(0.5, 0.5),
            region=(0.05, 0.35, 0.95, 0.53),
        )
    ]
    if english:
        layers.append(
            Layer(
                "translation",
                english,
                latin_font,
                font_size=16,
                anchor=(0.5, 0.56),
                region=(0.05, 0.53, 0.95, 0.68),
                direction="ltr",
                baseline_anchor="first",
                z_order=1,
            )
        )
    if titles:
        chapter_ids = {s.source.surah for s in excerpt.spans if s.source.surah}
        if len(chapter_ids) > 1:
            raise ReferenceError(
                "invalid_reference", "Title cues must refer to one chapter"
            )
        surah = title_surah or next(iter(chapter_ids), None)
        if chapter_ids and title_surah and title_surah not in chapter_ids:
            raise ReferenceError(
                "invalid_reference", "Title chapter does not match source"
            )
        if surah is None:
            # Caller must supply an actual upcoming chapter for an opening basmala.
            raise ReferenceError(
                "invalid_reference",
                "Separate basmala needs an explicit title override or titles disabled",
            )
        chapter = QuranDataClient().get_chapter(surah)
        layers.extend(
            (
                Layer(
                    "arabic_title",
                    arabic_title or f"سورة {chapter.name_arabic}",
                    arabic_font,
                    font_size=25,
                    anchor=(0.5, 0.16),
                    region=(0.05, 0.08, 0.95, 0.18),
                    persistent=True,
                ),
                Layer(
                    "latin_title",
                    latin_title or f"Surah {chapter.name_simple}",
                    latin_font,
                    font_size=15,
                    anchor=(0.5, 0.20),
                    region=(0.05, 0.18, 0.95, 0.25),
                    direction="ltr",
                    persistent=True,
                ),
            )
        )
    if logo:
        layers.append(
            Layer(
                "logo",
                image=logo,
                anchor=(0.5, 0.9),
                region=(0.35, 0.84, 0.65, 0.96),
                persistent=True,
                z_order=5,
            )
        )
    return Scene(width, height, tuple(layers))
