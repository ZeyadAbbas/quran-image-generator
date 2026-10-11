"""Pinned font inspection and reproducible face/axis materialization."""

from __future__ import annotations

import copy
import hashlib
import tempfile
import unicodedata
from dataclasses import replace
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTCollection, TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from .references import ReferenceError


def _face(path: str, index: int) -> TTFont:
    with Path(path).open("rb") as stream:
        collection = stream.read(4) == b"ttcf"
    if not collection and index != 0:
        raise ReferenceError("invalid_font_face", "An ordinary font has only face 0", details={"field": "font_face", "value": index, "allowed": [0]})
    try:
        return TTFont(path, fontNumber=index if collection else -1, recalcTimestamp=False)
    except Exception as error:
        raise ReferenceError("invalid_font_face", "Font face cannot be loaded", details={"field": "font_face", "value": index}) from error


def _name(font: TTFont, identifier: int) -> str:
    return font["name"].getDebugName(identifier) or ""


def missing_codepoints(font: TTFont, text: str) -> list[int]:
    cmap = font.getBestCmap() or {}
    return sorted({ord(c) for c in text if not c.isspace() and unicodedata.category(c) != "Cf"
                   and (ord(c) not in cmap or cmap[ord(c)] == ".notdef")})


def _axes(font: TTFont, values: dict[str, float]) -> dict[str, float]:
    from .contract_schema import AXES
    from .diagnostics import validate_schema

    validate_schema(values, AXES, prefix="/variation_axes")
    available = {a.axisTag: a for a in font["fvar"].axes} if "fvar" in font else {}
    for tag, value in values.items():
        if tag not in available:
            raise ReferenceError("unknown_font_axis", "Axis is absent from the selected font", details={"field": "variation_axes", "path_suffix": "/" + tag, "value": tag, "allowed": list(available)})
        axis = available[tag]
        if not axis.minValue <= value <= axis.maxValue:
            raise ReferenceError("invalid_font_axis", "Axis value is outside the selected font range", details={"field": "variation_axes", "path_suffix": "/" + tag, "value": value, "allowed": [axis.minValue, axis.maxValue]})
    return {tag: float(values.get(tag, axis.defaultValue)) for tag, axis in available.items()}


def _features(font: TTFont, features: tuple[str, ...] | list[str], text: str) -> None:
    available = {record.FeatureTag for table in ("GSUB", "GPOS") if table in font and font[table].table.FeatureList
                 for record in font[table].table.FeatureList.FeatureRecord}
    mandatory = {"ccmp", "rlig", "curs", "mark", "mkmk", "init", "medi", "fina", "isol"}
    arabic = any("ARABIC" in unicodedata.name(c, "") for c in text)
    for index, feature in enumerate(features):
        tag = feature.lstrip("+-").split("=", 1)[0]
        disabled = feature.startswith("-") or feature.endswith("=0")
        if arabic and tag in mandatory and disabled:
            raise ReferenceError("required_shaping_feature", "Required Arabic shaping features cannot be disabled", details={"field": "font_features", "path_suffix": f"/{index}", "value": feature})
        if tag not in available:
            raise ReferenceError("unknown_font_feature", "Feature is absent from the selected font", details={"field": "font_features", "path_suffix": f"/{index}", "value": feature, "allowed": sorted(available)})


@lru_cache(maxsize=32)
def _font_metadata(path: str, digest: str, font_face: int, axis_values: tuple[tuple[str, float], ...], font_size: float) -> dict[str, Any]:
    variation_axes = dict(axis_values)
    text, role, license, attribution = "", "", "", ""
    from .scenes import checked_asset

    path = str(path)
    checked_asset(path, digest)
    if len(text) > 8000 or not 1 <= font_size <= 512 or type(font_face) is not int or not 0 <= font_face <= 31:
        raise ReferenceError("invalid_request", "Font inspection exceeds text/size/face bounds")
    faces = []
    with Path(path).open("rb") as stream:
        collection = stream.read(4) == b"ttcf"
    if collection:
        selected = TTCollection(path, lazy=True)
        try:
            if len(selected.fonts) > 32:
                raise ReferenceError("resource_limit", "Font collections are limited to 32 faces")
            faces = [{"index": i, "family": _name(f, 1), "subfamily": _name(f, 2)} for i, f in enumerate(selected.fonts)]
        finally:
            selected.close()
    with _face(path, font_face) as font:
        axes = _axes(font, variation_axes or {})
        variable_axes = [{"tag": a.axisTag, "minimum": a.minValue, "default": a.defaultValue, "maximum": a.maxValue,
                          "name": _name(font, a.axisNameID)} for a in font["fvar"].axes] if "fvar" in font else []
        instances = [{"name": _name(font, i.subfamilyNameID), "axes": i.coordinates} for i in font["fvar"].instances] if "fvar" in font else []
        metrics_font = instantiateVariableFont(font, axes, inplace=False) if variation_axes else font
        try:
            units = metrics_font["head"].unitsPerEm
            hhea = metrics_font["hhea"]
            missing = missing_codepoints(metrics_font, text)
            available = sorted({record.FeatureTag for table in ("GSUB", "GPOS") if table in font and font[table].table.FeatureList
                                for record in font[table].table.FeatureList.FeatureRecord})
            result = {"path": path, "sha256": digest, "role": role, "family": _name(font, 1), "subfamily": _name(font, 2),
                      "full_name": _name(font, 4), "postscript_name": _name(font, 6), "font_face": font_face,
                      "collection_faces": faces, "units_per_em": units,
                      "font_size_output_pixels": font_size,
                      "metrics": {"ascender": hhea.ascent, "descender": hhea.descent, "line_gap": hhea.lineGap,
                                  "ascender_pixels": hhea.ascent * font_size / units,
                                  "descender_pixels": hhea.descent * font_size / units,
                                  "line_gap_pixels": hhea.lineGap * font_size / units},
                      "variable_axes": variable_axes, "named_instances": instances, "effective_axes": axes,
                      "available_features": available, "license": license, "attribution": attribution,
                      "coverage": {"complete": not missing, "missing_codepoints": [f"U+{c:04X}" for c in missing],
                                   "missing_words": [word for word in text.split() if any(ord(c) in missing for c in word)]}}
            result["_codepoints"] = frozenset(c for c, glyph in (metrics_font.getBestCmap() or {}).items() if glyph != ".notdef")
        finally:
            if metrics_font is not font:
                metrics_font.close()
    return result


def inspect_font(path: str | Path, *, sha256: str = "", text: str = "", role: str = "", font_face: int = 0,
                 variation_axes: dict[str, float] | None = None, font_size: float = 30,
                 license: str = "", attribution: str = "") -> dict[str, Any]:
    """Inspect pinned bytes and selected-face metrics without shaping or output files."""
    from .contract_schema import AXES
    from .diagnostics import validate_schema
    from .scenes import checked_asset

    if len(text) > 8000 or not 1 <= font_size <= 512 or type(font_face) is not int or not 0 <= font_face <= 31:
        raise ReferenceError("invalid_request", "Font inspection exceeds text/size/face bounds")
    values = variation_axes or {}
    validate_schema(values, AXES, prefix="/variation_axes")
    digest = checked_asset(str(path), sha256)
    metadata = _font_metadata(str(path), digest, font_face, tuple(sorted(values.items())), font_size)
    result = copy.deepcopy({k: v for k, v in metadata.items() if k != "_codepoints"})
    points = metadata["_codepoints"]
    missing = {ord(c) for c in text if not c.isspace() and unicodedata.category(c) != "Cf" and ord(c) not in points}
    result.update(role=role, license=license, attribution=attribution,
                  coverage={"complete": not missing, "missing_codepoints": [f"U+{c:04X}" for c in sorted(missing)],
                            "missing_words": [word for word in text.split() if any(ord(c) in missing for c in word)]})
    return result


class FontWorkspace:
    """Lazy, job-local scratch files; no ambient fonts or persistent font downloads."""

    def __init__(self) -> None:
        self.temporary: tempfile.TemporaryDirectory[str] | None = None
        self.cache: dict[str, tuple[str, str]] = {}
        self.output_bytes = 0

    def __enter__(self) -> FontWorkspace:
        return self

    def __exit__(self, *args: Any) -> None:
        if self.temporary:
            self.temporary.cleanup()

    def materialize(self, path: str, digest: str, face: int, axes: dict[str, float]) -> tuple[str, str]:
        if not axes and face == 0:
            with Path(path).open("rb") as stream:
                if stream.read(4) != b"ttcf":
                    return path, digest
        from .snapshots import canonical_bytes

        key = hashlib.sha256(canonical_bytes({"font": digest, "face": face, "axes": axes})).hexdigest()
        if key not in self.cache:
            if len(self.cache) >= 64:
                raise ReferenceError("resource_limit", "At most 64 materialized font instances per job; split the batch")
            with _face(path, face) as font:
                values = _axes(font, axes)
                instance = instantiateVariableFont(font, values, inplace=False) if axes else font
                try:
                    buffer = BytesIO()
                    instance.recalcTimestamp = False
                    instance.save(buffer)
                    data = buffer.getvalue()
                finally:
                    if instance is not font:
                        instance.close()
            if len(data) > 32_000_000 or self.output_bytes + len(data) > 128_000_000:
                raise ReferenceError("resource_limit", "Materialized font scratch budget exceeds 128 MB; split the batch")
            self.output_bytes += len(data)
            if not self.temporary:
                self.temporary = tempfile.TemporaryDirectory(prefix="qig-font-faces-")
            output = Path(self.temporary.name) / f"{key}.ttf"
            output.write_bytes(data)
            self.cache[key] = str(output), hashlib.sha256(data).hexdigest()
        return self.cache[key]

    def prepare_scene(self, scene: Any, assets: dict[str, Any] | None = None) -> Any:
        return replace(scene, layers=tuple(self.prepare(layer, primary_terms=(assets or {}).get(layer.role, {})) for layer in scene.layers))

    def prepare(self, layer: Any, *, primary_terms: dict[str, Any] | None = None) -> Any:
        from .style_contract import validate_layer_style

        validate_layer_style(layer)
        if not layer.enabled or not layer.text or layer.image:
            return layer
        from .scenes import checked_asset

        text = layer.text + ("" if layer.decoration_font else layer.suffix)
        if layer.decoration_font:
            for marker in layer.inline_markers:
                text = text.replace(marker, "")
        primary = {"path": layer.font, "sha256": checked_asset(layer.font, layer.sha256), "font_face": layer.font_face,
                   "variation_axes": layer.variation_axes, "license": (primary_terms or {}).get("license", "See THIRD_PARTY_NOTICES.md"),
                   "attribution": (primary_terms or {}).get("attribution", "Bundled font; see third-party notices")}
        candidates = [primary, *layer.font_fallbacks]
        inputs = []
        choice = None
        details = None
        coverage = []
        for index, candidate in enumerate(candidates):
            try:
                digest = checked_asset(candidate["path"], candidate["sha256"])
                info = inspect_font(candidate["path"], sha256=digest, text=text, role=layer.role,
                                    font_face=candidate.get("font_face", 0), variation_axes=candidate.get("variation_axes", {}),
                                    license=candidate.get("license", ""), attribution=candidate.get("attribution", ""))
            except ReferenceError as error:
                error.details = getattr(error, "details", {})
                if index:
                    error.details["path_suffix"] = f"/{index - 1}/" + error.details.get("field", "path") + error.details.get("path_suffix", "")
                    error.details["field"] = "font_fallbacks"
                error.details["role"] = layer.role
                raise
            inputs.append({"path": candidate["path"], "sha256": digest, "license": info["license"], "attribution": info["attribution"]})
            coverage.append({"sha256": digest, "coverage": info["coverage"]})
            if choice is None and info["coverage"]["complete"]:
                choice, details = candidate, info
        if choice is None:
            # A whole-layer fallback keeps bidi context, joins and every mark
            # together. No per-codepoint substitution is ever attempted.
            raise ReferenceError("missing_glyph", "No explicitly pinned font covers the complete shaped layer", details={
                "role": layer.role, "field": "font_fallbacks", "candidates": coverage, "fallback_policy": "whole_layer"})
        if layer.font_features:
            with _face(choice["path"], choice.get("font_face", 0)) as font:
                _features(font, layer.font_features, text)
        path, digest = self.materialize(choice["path"], choice["sha256"], choice.get("font_face", 0), choice.get("variation_axes", {}))
        return replace(layer, resolved_font=path, resolved_font_sha256=digest,
                       font_info={"inputs": inputs, "effective": details, "derived_sha256": digest,
                                  "features": layer.font_features, "language": layer.font_language,
                                  "fallback_policy": "whole_layer", "fallback_used": choice is not primary})
