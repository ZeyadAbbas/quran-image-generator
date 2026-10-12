"""Source-associated decoration runs; never identify markers by their glyph text."""

from __future__ import annotations

import copy
import math
import re
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter

from .caption_fit import FitError, pixel_region, within
from .font_controls import FontWorkspace
from .references import ReferenceError
from .scenes import Layer, LayerPlan, Scene, _color_mask, checked_asset, layer_font

ELEMENT_FIELDS = ("enabled", "color", "opacity", "outline_width", "outline_color", "shadow_offset", "shadow_blur",
                  "shadow_color", "shadow_opacity", "font_face", "variation_axes", "font_features", "font_language",
                  "font_fallbacks", "direction")


def prepare_element_fonts(layer: Layer, assets: dict[str, Any], root: Path, workspace: FontWorkspace) -> Layer:
    if layer.decoration_layout != "elements":
        return layer
    inherited = layer.font_info["effective"] if layer.font_info else {}
    fonts, styles = {}, {}
    for kind, field in (("quotes", "quotation_style"), ("markers", "marker_style")):
        style = {name: getattr(layer, name) for name in ELEMENT_FIELDS}
        style.update(getattr(layer, field))
        style.setdefault("offset", (0, 0))
        selector = assets.get(kind) or assets.get("decorations")
        if selector:
            source = Path(selector["path"])
            source = source.resolve() if source.is_absolute() else (root / source).resolve()
            path, digest = str(source), checked_asset(str(source), selector["sha256"])
            # Font settings belong to the separately selected face, rather than
            # transferring axis names from an unrelated body face.
            for option, default in (("font_face", 0), ("variation_axes", {}), ("font_features", ()), ("font_language", ""), ("font_fallbacks", ())):
                style[option] = getattr(layer, field).get(option, default)
        else:
            path = inherited.get("path", layer.font)
            digest = inherited.get("sha256", checked_asset(path))
            style["font_face"] = getattr(layer, field).get("font_face", inherited.get("font_face", layer.font_face))
            style["variation_axes"] = getattr(layer, field).get("variation_axes", inherited.get("effective_axes", layer.variation_axes))
        style["font_fallbacks"] = tuple({**asset, "path": str((root / asset["path"]).resolve())} if not Path(asset["path"]).is_absolute() else dict(asset)
                                        for asset in style["font_fallbacks"])
        text = ((layer.quote_open if layer.quote_open_enabled else "") + (layer.quote_close if layer.quote_close_enabled else "")) if kind == "quotes" and layer.ornaments else " ".join(v["text"] for v in layer.marker_specs) if kind == "markers" else ""
        selected = Layer(kind, text=text, font=path, sha256=digest, font_size=layer.font_size, min_font_size=1,
                         required=False, **{name: style[name] for name in ELEMENT_FIELDS})
        try:
            Scene(576, 1024, (selected,)).validate()
            selected = workspace.prepare(selected, primary_terms=selector or inherited)
        except ReferenceError as error:
            details = getattr(error, "details", {})
            details["role"] = "arabic"
            name = details.get("field", "font")
            if details.get("path", "").startswith("/layers/"):
                name = details["path"].split("/")[-1]
            details["path"] = "/profile/styles/arabic/" + field + "/" + name + details.get("path_suffix", "")
            error.details = details
            raise
        fonts[kind] = asdict(selected)
        styles[field] = style
    info = dict(layer.font_info or {})
    info["inputs"] = list(info.get("inputs", [])) + [asset for font in fonts.values() if font["font_info"] for asset in font["font_info"]["inputs"]]
    return replace(layer, element_fonts=fonts, font_info=info, quotation_style=styles["quotation_style"], marker_style=styles["marker_style"])


def _font_layer(layer: Layer, kind: str) -> Layer:
    if kind == "body":
        return layer
    values = layer.element_fonts.get("quotes" if kind.startswith("quote") else "markers")
    if values is None:
        raise ReferenceError("unresolved_font", "Prepare independent decoration fonts with prepare_element_fonts before planning")
    return Layer(**values)


def _style(layer: Layer, kind: str) -> dict[str, Any]:
    if kind == "body":
        return {name: getattr(layer, name) for name in ELEMENT_FIELDS}
    return layer.quotation_style if kind.startswith("quote") else layer.marker_style


def _effect_box(box: tuple[float, float, float, float], style: dict[str, Any], scale: float) -> tuple[float, float, float, float]:
    stroke = math.ceil(style.get("outline_width", 0) * scale)
    blur = math.ceil(4 * style.get("shadow_blur", 0) * scale) if style.get("shadow_opacity", 0) else 0
    dx, dy = (v * scale for v in style.get("shadow_offset", (0, 0))) if style.get("shadow_opacity", 0) else (0, 0)
    return (box[0] - stroke - blur + min(0, dx), box[1] - stroke - blur + min(0, dy),
            box[2] + stroke + blur + max(0, dx), box[3] + stroke + blur + max(0, dy))


def _union(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _items(layer: Layer) -> list[dict[str, Any]]:
    markers = {m["character_end"]: m for m in layer.marker_specs}
    result = []
    for word in re.finditer(r"\S+", layer.text):
        marker = markers.get(word.end()) if layer.marker_style.get("enabled", True) else None
        result.append({"text": word.group(), "start": word.start(), "end": word.end(), "marker": marker})
    return result


def _runs(layer: Layer, items: list[dict[str, Any]], *, first: bool, last: bool) -> list[dict[str, Any]]:
    runs = []
    quotes = layer.ornaments and layer.quotation_style.get("enabled", True)
    if first and quotes and layer.quote_open_enabled and layer.quote_open:
        runs.append({"id": "quote:open", "kind": "quote_open", "text": layer.quote_open})
    words = []
    final_marker = None
    for item in items:
        words.append(item["text"])
        if item["marker"]:
            runs.append({"kind": "body", "text": " ".join(words)})
            words = []
            marker = {**item["marker"], "kind": "marker"}
            if last and item is items[-1] and layer.marker_placement == "after_quote":
                final_marker = marker
            else:
                runs.append(marker)
    if words:
        runs.append({"kind": "body", "text": " ".join(words)})
    if last and quotes and layer.quote_close_enabled and layer.quote_close:
        runs.append({"id": "quote:close", "kind": "quote_close", "text": layer.quote_close})
    if final_marker:
        runs.append(final_marker)
    return runs


def _measure(layer: Layer, items: list[dict[str, Any]], size: float, scale: float, first: bool, last: bool) -> tuple[list[dict[str, Any]], tuple[float, float, float, float]]:
    runs = _runs(layer, items, first=first, last=last)
    boxes, cursor = [], 0.0
    for index, run in enumerate(runs):
        kind = run["kind"]
        selected = _font_layer(layer, kind)
        selected_size = size if kind == "body" else size * layer.decoration_scale if kind.startswith("quote") else max(1, round(size * layer.suffix_scale))
        try:
            font = layer_font(selected, selected_size)
            box = font.getbbox(run["text"])
        except ReferenceError as error:
            error.details = {**getattr(error, "details", {}), "role": "arabic", "element_id": run.get("id", "body")}
            if error.code == "resource_limit":
                error.details.update(field="decoration_scale" if kind.startswith("quote") else "font_size", effective_size=selected_size)
            elif kind != "body" and "field" in error.details:
                field = "quotation_style" if kind.startswith("quote") else "marker_style"
                error.details["path"] = "/profile/styles/arabic/" + field + "/" + error.details["field"] + error.details.get("path_suffix", "")
            raise
        width = box[2] - box[0]
        x = -cursor - box[2] if layer.direction == "rtl" else cursor - box[0]
        style = _style(layer, kind)
        ox, oy = style.get("offset", (0, 0))
        y = layer.suffix_offset * scale if kind == "marker" else 0
        x, y = x + ox * scale, y + oy * scale
        ink = (x + box[0], y + box[1], x + box[2], y + box[3])
        effects = _effect_box(ink, style, scale)
        run.update(x=x, y=y, font_size=selected_size, glyph_bounds=ink, bounds=effects, style=style,
                   font_sha256=selected.resolved_font_sha256 or selected.sha256)
        if selected.font_info:
            effective = selected.font_info["effective"]
            run["effective_font"] = {"source_sha256": effective["sha256"], "derived_sha256": selected.font_info["derived_sha256"],
                                     "font_face": effective["font_face"], "axes": effective["effective_axes"],
                                     "features": selected.font_info["features"], "language": selected.font_info["language"],
                                     "metrics": {name + "_pixels": effective["metrics"][name] * selected_size / effective["units_per_em"]
                                                 for name in ("ascender", "descender", "line_gap")}}
        boxes.append(effects)
        cursor += width
        if index < len(runs) - 1:
            following = runs[index + 1]["kind"]
            gap = layer.quote_spacing if kind.startswith("quote") or following.startswith("quote") else layer.suffix_spacing if kind == "marker" or following == "marker" else layer.word_spacing * size / scale
            cursor += gap * scale
    return runs, _union(boxes)


def plan_elements(scene: Scene, layer: Layer, digest: str) -> LayerPlan:
    if layer.direction != "rtl":
        raise ReferenceError("unsupported_decoration_direction", "Source-associated Quran elements require RTL paragraph direction", details={"path": "/profile/styles/arabic/direction", "role": "arabic", "allowed": ["rtl"]})
    items = _items(layer)
    if not items:
        raise ReferenceError("missing_asset", "Caption has no visible source text")
    scale = scene.width / 576
    allowed = pixel_region(scene, layer)
    margin = layer.safe_margin * scale
    width = allowed[2] - allowed[0] - 2 * margin
    preferred = max(1, round(layer.font_size * scale, 2) if isinstance(layer.font_size, float) else round(layer.font_size * scale))
    minimum = max(1, round(layer.min_font_size * scale))
    sizes = [max(minimum, preferred - n) for n in range(math.ceil(preferred - minimum) + 1)] if layer.fit == "shrink" else [preferred]
    last_bounds, last_lines = (0, 0, 0, 0), 0
    for size in sizes:
        lines: list[list[dict[str, Any]]] = []
        start = 0
        while start < len(items):
            end = start + 1
            while end < len(items):
                # A forced break follows the complete source word/marker unit.
                if items[end - 1]["end"] in layer.forced_breaks:
                    break
                _, candidate = _measure(layer, items[start:end + 1], size, scale, not lines, end == len(items) - 1)
                if candidate[2] - candidate[0] > width:
                    candidates = [i for i in range(start + 1, end + 1) if items[i - 1]["end"] in layer.preferred_breaks]
                    if candidates:
                        end = max(candidates)
                    break
                end += 1
            lines.append(items[start:end])
            start = end
        measured = [_measure(layer, line, size, scale, index == 0, index == len(lines) - 1) for index, line in enumerate(lines)]
        height = max(box[3] - box[1] for _, box in measured)
        step = size * layer.line_height if layer.line_height else height + layer.line_spacing * scale
        positioned = []
        elements: list[dict[str, Any]] = []
        boxes, ink_boxes = [], []
        for index, (line, (runs, box)) in enumerate(zip(lines, measured, strict=True)):
            y = layer.anchor[1] * scene.height + (index - (len(lines) - 1 if layer.baseline_anchor == "last" else 0)) * step
            x = (layer.anchor[0] * scene.width - (box[0] + box[2]) / 2 if layer.alignment == "center" else
                 allowed[0] + margin - box[0] if layer.alignment == "left" else allowed[2] - margin - box[2])
            positioned.append((" ".join(item["text"] for item in line), x, y))
            for run in runs:
                run["x"], run["y"] = run["x"] + x, run["y"] + y
                for name in ("glyph_bounds", "bounds"):
                    b = run[name]
                    run[name] = (math.floor(b[0] + x), math.floor(b[1] + y), math.ceil(b[2] + x), math.ceil(b[3] + y))
                run["line_index"] = index
                run["id"] = run.get("id", f"body:{index}:{len(elements)}")
                elements.append(run)
                boxes.append(run["bounds"])
                ink_boxes.append(run["glyph_bounds"])
        envelope = _union(boxes)
        bounds = (math.floor(envelope[0] - margin), math.floor(envelope[1] - margin), math.ceil(envelope[2] + margin), math.ceil(envelope[3] + margin))
        last_bounds, last_lines = bounds, len(lines)
        collision = layer.line_height and any(measured[i - 1][1][3] > measured[i][1][1] + step for i in range(1, len(lines)))
        if len(lines) <= layer.max_lines and within(bounds, allowed) and not collision:
            ink = _union(ink_boxes)
            info = copy.deepcopy(layer.font_info)
            if info:
                effective = info["effective"]
                effective["font_size_output_pixels"] = size
                for metric in ("ascender", "descender", "line_gap"):
                    effective["metrics"][metric + "_pixels"] = effective["metrics"][metric] * size / effective["units_per_em"]
            return LayerPlan(layer, tuple(positioned), bounds, size, digest, elements=tuple(elements), glyph_bounds=(int(ink[0]), int(ink[1]), int(ink[2]), int(ink[3])),
                             decoration_asset_sha256=checked_asset(layer.decoration_font) if layer.decoration_font else "",
                             font_info=info,
                             typography={"baseline_step": step, "baselines": [v[2] for v in positioned], "word_spacing_pixels": size * layer.word_spacing,
                                         "forced_breaks": layer.forced_breaks, "preferred_breaks": layer.preferred_breaks, "decoration_layout": "elements"})
    if layer.line_height and collision:
        raise ReferenceError("line_height_collision", "Configured baseline step overlaps decorated line envelopes", details={
            "path": "/profile/styles/arabic/line_height", "role": "arabic", "baseline_step": step, "bounds": last_bounds,
            "allowed": allowed, "suggestions": ["increase_line_height", "reduce_effects"]})
    raise FitError(layer.role, last_bounds, allowed, sizes[-1], last_lines)


def paint_elements(scene: Scene, plan: LayerPlan, image: Image.Image) -> None:
    layer = plan.layer
    scale = scene.width / 576
    for category in ("body", "quotes", "markers"):
        runs = [v for v in plan.elements if ("quotes" if v["kind"].startswith("quote") else "markers" if v["kind"] == "marker" else "body") == category]
        if not runs:
            continue
        with Image.new("RGBA", image.size) as glyphs:
            for run in runs:
                font_layer = _font_layer(layer, run["kind"])
                checked_asset(font_layer.resolved_font or font_layer.font, font_layer.resolved_font_sha256 or font_layer.sha256)
                layer_font(font_layer, run["font_size"]).paint(glyphs, run["text"], run["x"], run["y"], "#FFFFFF")
            style = runs[0]["style"]
            opacity = style["opacity"]
            with glyphs.getchannel("A") as mask:
                if style["shadow_opacity"]:
                    with mask.filter(ImageFilter.GaussianBlur(style["shadow_blur"] * scale)) as blur, Image.new("L", image.size) as moved:
                        moved.paste(blur, tuple(round(v * scale) for v in style["shadow_offset"]))
                        _color_mask(image, moved, style["shadow_color"], style["shadow_opacity"] * opacity)
                stroke = round(style["outline_width"] * scale)
                if stroke:
                    with mask.filter(ImageFilter.MaxFilter(2 * stroke + 1)) as outline:
                        _color_mask(image, outline, style["outline_color"], opacity)
                _color_mask(image, mask, style["color"], opacity)
