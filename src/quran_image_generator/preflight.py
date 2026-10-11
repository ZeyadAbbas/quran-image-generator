"""Actionable native/runtime/content checks before an external export."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from .bindings import BindingDataset
from .content import _load_bundled_corpus
from .references import CorpusIdentity, ReferenceError, bridge_data
from .resources import asset_path
from .scenes import Layer, check_glyphs, checked_asset, layer_font
from .snapshots import SnapshotStore


def preflight(data: dict[str, Any], root: Path) -> dict[str, Any]:
    from .api import _local_path, runtime_identity

    runtime = runtime_identity()
    if runtime["imagemagick"] == "unavailable":
        raise ReferenceError(
            "missing_native_runtime",
            "Install ImageMagick native libraries; on Windows set MAGICK_HOME to the DLL directory, on Linux install imagemagick/libmagickwand",
        )
    if not runtime["pillow_raqm"] and not runtime["native_raqm"]:
        raise ReferenceError(
            "missing_shaping",
            "Use a Pillow or ImageMagick build with RAQM/Harfbuzz Arabic shaping",
        )
    CorpusIdentity(**data.get("source_corpus", {})).validate()
    _load_bundled_corpus()
    bridge_data()
    checks: dict[str, Any] = {
        "native_runtime": runtime,
        "corpus": "verified",
        "mapping": "verified",
        "assets": {},
        "translations": "disabled",
        "output": "not_requested",
    }
    selected_assets = dict(data.get("assets", {}))
    for role in ("arabic", "translation", "arabic_title", "latin_title"):
        if role not in selected_assets:
            path = str(
                asset_path("fonts", "quran_font.ttf")
                if role in ("arabic", "arabic_title")
                else asset_path("fonts", "multilingual_fonts", "am.ttf")
            )
            selected_assets[role] = {"path": path, "sha256": checked_asset(path)}
    for role, asset in selected_assets.items():
        path = str(_local_path(asset["path"], root))
        digest = checked_asset(path, asset["sha256"])
        if role == "logo" and not asset.get("glyph"):
            with Image.open(path) as image:
                if image.width * image.height > 16_000_000:
                    raise ReferenceError(
                        "resource_limit", "Logo exceeds 16 million pixels"
                    )
                image.verify()
        else:
            sample = asset.get("glyph") or {
                "decorations": "{ } (0123456789)",
                "arabic_title": "سورة لقمان",
                "arabic": "خَٰلِدِينَ فِيهَا",
            }.get(role, "Surah caption 0123456789")
            layer = Layer(
                role,
                sample,
                path,
                direction="rtl" if role in ("arabic", "arabic_title") else "ltr",
            )
            check_glyphs(layer)
            left, top, right, bottom = layer_font(layer, 30).getbbox(sample)
            if right <= left or bottom <= top:
                raise ReferenceError(
                    "missing_glyph",
                    f"{role} font maps the selected symbol to empty ink",
                )
        checks["assets"][role] = {"sha256": digest, "status": "ready"}
    if "translation_dataset" in data:
        BindingDataset.from_dict(data["translation_dataset"])
        checks["translations"] = "verified_import"
    if "translation_snapshot" in data:
        pin = data["translation_snapshot"]
        SnapshotStore(_local_path(pin["directory"], root)).bindings(pin["sha256"])
        checks["translations"] = "verified_offline_snapshot"
    if data.get("output_directory"):
        output = _local_path(data["output_directory"], root)
        try:
            output.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=output) as stream:
                stream.write(b"preflight")
                stream.flush()
        except OSError as error:
            raise ReferenceError(
                "output_io",
                "Output directory is not writable; choose a writable caller-owned location",
            ) from error
        checks["output"] = "writable"
    return {"ready": True, "checks": checks}
