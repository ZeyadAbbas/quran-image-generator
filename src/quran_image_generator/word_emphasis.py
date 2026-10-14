"""Public, source-associated word selection states over one approved layout."""

from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageMath

from .batching import AssetCache
from .caption_fit import pixel_region, within
from .excerpts import Excerpt
from .references import ReferenceError
from .render_cache import CaptionRenderCache
from .scenes import LayerPlan, Scene, render_layer
from .snapshots import canonical_bytes
from .word_masks import WordUnit, error, word_units

CONTRACT_VERSION = 1


def descriptor(backend: str, shaping: bool) -> dict[str, Any]:
    from .contract_schema import WORD_EMPHASIS, WORD_STATE

    return {
        "version": CONTRACT_VERSION,
        "representation": "selection_state_variants",
        "supported": backend == "pillow" and shaping,
        "backend_support": {"pillow_raqm": True, "imagemagick_raqm": False},
        "configuration_schema": WORD_EMPHASIS,
        "state_schema": WORD_STATE,
        "selector": ["cue_id", "span_occurrence", "source_word"],
        "layout_stable": True,
        "paint": ["fill", "background", "both"],
        "weight": {"minimum": 0, "maximum": 1, "interpolation": "linear_sRGB_channels"},
        "atomic_policy": "equal_weights_required_for_all_members",
        "mask_scope": "fill_ink_only; outlines_and_shadows_rendered_once_unchanged",
        "inline_decoration_overlap": "static_decoration_pixels_take_precedence",
        "background": {
            "geometry": "per_shaped_ink_part",
            "units": ["em", "output_pixels"],
            "overlap": "maximum_opacity",
            "corner_radius": "clamped_to_half_short_side",
        },
        "defaults": {
            "mode": "fill",
            "active_color": "existing_arabic_color",
            "inactive_color": "existing_sRGB_channels_times_0.35",
            "default_weight": 1,
        },
        "limits": {
            "source_display_groups_per_cue": 128,
            "states_per_cue": 32,
            "unique_assets_per_batch": 512,
            "output_bytes_per_batch": 512_000_000,
            "mask_bytes_per_batch": 128 * 1024 * 1024,
            "mask_bytes_per_cue": 64 * 1024 * 1024,
            "mask_probe_operations_per_cue": 4096,
        },
        "timing_owner": "consumer",
    }


@dataclass
class PreparedWords:
    scene: Scene
    plan: LayerPlan
    units: list[WordUnit]
    options: dict[str, Any]
    layout_id: str
    backgrounds: list[list[dict[str, Any]]]

    def states(
        self, values: list[dict[str, Any]] | None
    ) -> list[tuple[str, list[float]]]:
        values = values if values is not None else [{"state_id": "all"}]
        seen = set()
        available = {
            (int(member["span_occurrence"]), int(member["source_word"]))
            for unit in self.units
            for member in unit.members
        }
        result = []
        for index, value in enumerate(values):
            path = f"/word_states/{index}"
            identifier = value["state_id"]
            if identifier in seen:
                raise error(
                    "duplicate_word_state",
                    "Each word state needs a unique ID",
                    path=path + "/state_id",
                )
            seen.add(identifier)
            default = float(value.get("default_weight", 1))
            selected: dict[tuple[int, int], float] = {}
            for word_index, word in enumerate(value.get("words", [])):
                key = word["span_occurrence"], word["source_word"]
                if key not in available:
                    raise error(
                        "invalid_word_selection",
                        "Selected source-word occurrence is outside this cue",
                        path=f"{path}/words/{word_index}",
                        selector=word,
                    )
                if key in selected:
                    raise error(
                        "duplicate_word_selection",
                        "Source-word occurrence is selected twice",
                        path=f"{path}/words/{word_index}",
                    )
                selected[key] = float(word["weight"])
            if not math.isfinite(default) or any(
                not math.isfinite(w) for w in selected.values()
            ):
                raise error(
                    "invalid_word_selection", "Word weights must be finite", path=path
                )
            weights = []
            for unit in self.units:
                resolved = {
                    selected.get(
                        (int(member["span_occurrence"]), int(member["source_word"])),
                        default,
                    )
                    for member in unit.members
                }
                if len(resolved) != 1:
                    raise error(
                        "atomic_word_split",
                        "An indivisible source/display or shaped-ink group needs equal member weights",
                        path=path + "/words",
                        members=unit.members,
                        reasons=sorted(unit.reasons),
                    )
                weights.append(float(resolved.pop()))
            result.append((identifier, weights))
        return result

    def metadata(self) -> dict[str, Any]:
        result = []
        for index, unit in enumerate(self.units):
            parts = [
                {
                    "line_index": part.line_index,
                    "run_id": part.run_id,
                    "run_character_ranges": part.ranges,
                    "run_text": part.text,
                    "ink_bounds": part.bounds,
                    "mask_font_sha256": part.mask_font_sha256,
                    "protected_decoration_pixels": part.protected_pixels,
                }
                for part in unit.parts
            ]
            result.append(
                {
                    "unit_id": f"word:{index}",
                    "members": unit.members,
                    "atomic": len(unit.members) > 1 or bool(unit.reasons),
                    "atomic_reasons": sorted(unit.reasons),
                    "display_ranges": [
                        {"character_range": [a, b], "text": self.plan.layer.text[a:b]}
                        for a, b in unit.ranges
                    ],
                    "parts": parts,
                    "backgrounds": self.backgrounds[index],
                }
            )
        return {
            "version": CONTRACT_VERSION,
            "representation": "selection_state_variants",
            "layout_id": self.layout_id,
            "options": self.options,
            "units": result,
            "states": [],
        }

    def painter(self, weights: list[float]) -> WordPainter:
        return WordPainter(self, weights)


def prepare_words(
    excerpt: Excerpt,
    scene: Scene,
    plans: tuple[LayerPlan, ...],
    options: dict[str, Any],
    runtime: dict[str, Any],
    checkpoint: Callable[[], None] | None = None,
) -> PreparedWords:
    plan = next((item for item in plans if item.layer.role == "arabic"), None)
    if plan is None:
        raise error(
            "unsupported_word_emphasis_option",
            "Word emphasis requires the Arabic layer",
        )
    units = word_units(
        excerpt,
        plan,
        scene.render_backend,
        quotations=options.pop("_quotations", False),
        verse_numbers=options.pop("_verse_numbers", False),
        checkpoint=checkpoint,
    )
    background = {
        "color": "#FFD54F",
        "opacity": 0.35,
        "padding": [0.15, 0.08],
        "corner_radius": 0.12,
        "unit": "em",
        **options.get("background", {}),
    }
    options = {"mode": "fill", **options, "background": background}
    if options["mode"] == "background" and any(
        key in options for key in ("active_color", "inactive_color")
    ):
        raise error(
            "unsupported_word_emphasis_option",
            "Background-only emphasis keeps the original text fill; use both to recolor text",
        )
    dimensions = [
        *background["padding"],
        background["corner_radius"],
        background["opacity"],
    ]
    if not all(math.isfinite(value) for value in dimensions):
        raise error(
            "invalid_word_emphasis",
            "Word background dimensions and opacity must be finite",
        )
    factor = plan.font_size if background["unit"] == "em" else 1
    px, py = (v * factor for v in background["padding"])
    allowed = (
        (plan.layout_info or {}).get("group_region")
        or (plan.layout_info or {}).get("allowed")
        or pixel_region(scene, plan.layer)
    )
    backgrounds = []
    for unit in units:
        boxes = []
        for part in unit.parts:
            left, top, right, bottom = part.bounds
            box = (
                math.floor(left - px),
                math.floor(top - py),
                math.ceil(right + px),
                math.ceil(bottom + py),
            )
            if options["mode"] in ("background", "both") and not within(box, allowed):
                raise error(
                    "word_background_overflow",
                    "Word background cannot fit without changing the approved layout",
                    path="/word_emphasis/background/padding",
                    actual=box,
                    allowed=allowed,
                    members=unit.members,
                )
            radius = min(
                background["corner_radius"] * factor,
                (box[2] - box[0]) / 2,
                (box[3] - box[1]) / 2,
            )
            boxes.append(
                {
                    "line_index": part.line_index,
                    "rect": box,
                    "corner_radius_pixels": radius,
                }
            )
        backgrounds.append(boxes)
    visual = asdict(plan)
    visual["layer"]["resolved_font"] = ""
    for font in visual["layer"].get("element_fonts", {}).values():
        font["resolved_font"] = ""
    identity = {
        "scene": [scene.width, scene.height],
        "backend": scene.render_backend,
        "plan": visual,
        "runtime": runtime,
        "word_contract": CONTRACT_VERSION,
        "members": [
            [
                {key: value for key, value in member.items() if key != "cue_id"}
                for member in unit.members
            ]
            for unit in units
        ],
        "mask_fonts": [part.mask_font_sha256 for unit in units for part in unit.parts],
    }
    layout_id = hashlib.sha256(canonical_bytes(identity)).hexdigest()
    return PreparedWords(scene, plan, units, options, layout_id, backgrounds)


def render_word_states(
    prepared: PreparedWords,
    entry: dict[str, Any],
    shared: dict[str, dict[str, Any]],
    staging: Path,
    cropped: bool,
    disk: AssetCache | None,
    cache: CaptionRenderCache | None,
    previous_bytes: int,
    checkpoint: Callable[[], None],
) -> int:
    base_id = next(
        layer["asset_id"]
        for layer in entry["layers"]
        if layer["layer"]["role"] == "arabic"
    )
    added_bytes = 0
    for state in entry["word_emphasis"]["states"]:
        checkpoint()
        weights = [record["weight"] for record in state["weights"]]
        key = hashlib.sha256(
            canonical_bytes(
                {
                    "base_asset": base_id,
                    "layout": prepared.layout_id,
                    "contract": CONTRACT_VERSION,
                    "options": prepared.options,
                    "weights": weights,
                }
            )
        ).hexdigest()
        if (
            prepared.options["mode"] == "fill"
            and all(weight == 1 for weight in weights)
            and ImageColor.getrgb(
                prepared.options.get("active_color", prepared.plan.layer.color)
            )
            == ImageColor.getrgb(prepared.plan.layer.color)
        ) or (prepared.options["mode"] == "background" and not any(weights)):
            key = base_id
        if key not in shared:
            if len(shared) >= 512:
                raise error(
                    "resource_limit", "Batch exceeds 512 unique assets; split the job"
                )
            path = staging / (key + ".png")
            remembered = cache.assets.get(key) if cache and disk is None else None
            if remembered is not None:
                raw, asset = remembered
                path.write_bytes(raw)
            else:
                asset = disk.restore(key, path) if disk else None
                if asset is None:
                    asset = render_layer(
                        prepared.scene,
                        prepared.plan,
                        path,
                        cropped=cropped,
                        word_paint=prepared.painter(weights),
                    )
                    if disk:
                        disk.store(key, path, asset)
            if cache and remembered is None:
                raw = path.read_bytes()
                cache.assets.put(key, (raw, asset), size=len(raw))
            added_bytes += path.stat().st_size
            if previous_bytes + added_bytes > 512_000_000:
                raise error(
                    "resource_limit",
                    "Batch exceeds 512 MB of PNG output; split the job",
                )
            shared[key] = {
                **shared[base_id],
                **asdict(asset),
                "asset_id": key,
                "path": path.name,
                "effect_bounds": asset.bounds,
            }
        state["asset_ids"] = [
            key if asset_id == base_id else asset_id for asset_id in entry["asset_ids"]
        ]
    return added_bytes


class WordPainter:
    """Replace only the existing fill operation; keep the original effect pass."""

    def __init__(self, prepared: PreparedWords, weights: list[float]) -> None:
        self.prepared, self.weights = prepared, weights

    def paint_backgrounds(self, image: Image.Image, opacity: float = 1) -> None:
        options = self.prepared.options
        if options["mode"] == "fill":
            return
        with Image.new("L", image.size) as combined:
            for weight, boxes in zip(
                self.weights, self.prepared.backgrounds, strict=True
            ):
                if not weight:
                    continue
                with Image.new("L", image.size) as shape:
                    draw = ImageDraw.Draw(shape)
                    for geometry in boxes:
                        left, top, right, bottom = geometry["rect"]
                        draw.rounded_rectangle(
                            (left, top, right - 1, bottom - 1),
                            radius=geometry["corner_radius_pixels"],
                            fill=round(
                                255
                                * options["background"]["opacity"]
                                * weight
                                * opacity
                            ),
                        )
                    with ImageChops.lighter(combined, shape) as union:
                        combined.paste(union)
            with Image.new(
                "RGBA", image.size, options["background"]["color"]
            ) as colors:
                colors.putalpha(combined)
                image.alpha_composite(colors)

    def paint_fill(
        self, image: Image.Image, mask: Image.Image, color: str, opacity: float
    ) -> None:
        base = ImageColor.getrgb(color)
        options = self.prepared.options
        active = ImageColor.getrgb(options.get("active_color", color))
        inactive = (
            ImageColor.getrgb(options["inactive_color"])
            if "inactive_color" in options
            else tuple(round(v * 0.35) for v in base)
        )
        with Image.new("RGBA", image.size, base + (255,)) as colored:
            if options["mode"] != "background":
                for unit, weight in zip(self.prepared.units, self.weights, strict=True):
                    rgb = tuple(
                        round(b + (a - b) * weight)
                        for a, b in zip(active, inactive, strict=True)
                    )
                    for part in unit.parts:
                        with part.image() as raw:
                            with raw.point(
                                lambda value: 255 if value else 0
                            ) as support:
                                colored.paste(rgb + (255,), part.bounds, support)
            with mask.point(lambda value: round(value * opacity)) as alpha:
                colored.putalpha(alpha)
            image.alpha_composite(colored)


def compose_word_state(
    response: Any, cue_index: int, state_id: str, size: tuple[int, int] | None = None
) -> Image.Image:
    """Checksum-verified composition using only a published selection state."""
    from .caption_editor import compose_caption

    data = (
        response.to_dict() if hasattr(response, "to_dict") else copy.deepcopy(response)
    )
    cue = data["cues"][cue_index]
    state = next(
        (
            item
            for item in cue.get("word_emphasis", {}).get("states", [])
            if item["state_id"] == state_id
        ),
        None,
    )
    if state is None:
        raise ReferenceError("invalid_word_state", "Unknown published word state")
    cue["asset_ids"] = state["asset_ids"]
    if size is None:
        size = tuple(cue["word_emphasis"]["canvas"])
    return compose_caption(data, cue_index, size)


def interpolate_word_states(
    a: Image.Image, b: Image.Image, progress: float
) -> Image.Image:
    """Linear premultiplied sRGB transition, without drawing glyph effects twice.

    The consumer owns timestamps and calls this on verified state compositions.
    Use endpoints from the same immutable layout and canvas.
    """
    if (
        type(progress) not in (float, int)
        or not math.isfinite(progress)
        or not 0 <= progress <= 1
    ):
        raise ReferenceError(
            "invalid_word_state",
            "Transition progress must be finite and between 0 and 1",
        )
    if a.size != b.size or a.mode != "RGBA" or b.mode != "RGBA":
        raise ReferenceError(
            "invalid_word_state", "State transitions need matching RGBA canvases"
        )
    if progress == 0 or progress == 1:
        return (a if progress == 0 else b).copy()
    with ExitStack() as images:

        def keep(value: Image.Image) -> Image.Image:
            images.callback(value.close)
            return value

        first_channels = [keep(value) for value in a.split()]
        second_channels = [keep(value) for value in b.split()]
        aa, ba = (
            keep(first_channels[3].convert("F")),
            keep(second_channels[3].convert("F")),
        )
        alpha = keep(
            ImageMath.lambda_eval(
                lambda e: e["a"] * (1 - progress) + e["b"] * progress, a=aa, b=ba
            )
        )
        channels = []
        for first, second in zip(first_channels[:3], second_channels[:3], strict=True):
            channels.append(
                keep(
                    ImageMath.lambda_eval(
                        lambda e: e["convert"](
                            (
                                e["a"] * e["aa"] * (1 - progress)
                                + e["b"] * e["ba"] * progress
                            )
                            / e["max"](e["alpha"], 1)
                            + 0.5,
                            "L",
                        ),
                        a=keep(first.convert("F")),
                        b=keep(second.convert("F")),
                        aa=aa,
                        ba=ba,
                        alpha=alpha,
                    )
                )
            )
        channels.append(
            keep(
                ImageMath.lambda_eval(
                    lambda e: e["convert"](e["a"] + 0.5, "L"), a=alpha
                )
            )
        )
        return Image.merge("RGBA", channels)
