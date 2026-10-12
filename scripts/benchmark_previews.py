"""Offline backend timings for cold, repeated and color-edited previews.

Run each backend in a fresh process for comparable cold caches. Times exclude
imports, GUI polling and image display; PNG output and caption input checks are
included. Outputs/metadata live only in the explicitly chosen output directory.
"""

from __future__ import annotations

import argparse
import json
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from quran_image_generator.api import execute_request, runtime_identity
from quran_image_generator.caption_editor import CaptionDocument
from quran_image_generator.content import QuranDataClient
from quran_image_generator.layout import build_layout
from quran_image_generator.models import GenerationRequest
from quran_image_generator.references import bridge_data
from quran_image_generator.render_cache import CaptionRenderCache
from quran_image_generator.rendering_backends import BackendMeasurer, BackendRenderer
from quran_image_generator.settings import load_settings, settings_from_mapping


def benchmark(root: Path, backend: str, config: Path | None = None) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    settings = load_settings(config) if config else settings_from_mapping({})
    settings = replace(settings, render_backend=backend, translations=())
    client, measurer, renderer = (
        QuranDataClient(),
        BackendMeasurer().for_backend(backend),
        BackendRenderer(),
    )
    results = []
    try:
        for case, selection in (
            ("fatiha", GenerationRequest(1, 1, 7)),
            ("kursi", GenerationRequest(2, 255, 255)),
        ):
            passage = client.fetch_passage(selection, ())
            for run in ("cold", "repeated", "color-edit"):
                chosen = (
                    replace(settings, quran_color="#EEEEEE")
                    if run == "color-edit"
                    else settings
                )
                start = time.perf_counter()
                layout = build_layout(passage, chosen, measurer)
                fitted = time.perf_counter()
                renderer.render(layout, chosen, root / f"{case}-{run}.png")
                end = time.perf_counter()
                results.append(
                    {
                        "case": case,
                        "run": run,
                        "layout_s": fitted - start,
                        "paint_s": end - fitted,
                        "total_s": end - start,
                    }
                )
                print(json.dumps(results[-1]), flush=True)
    finally:
        renderer.close()
    base = CaptionDocument(root=root).request().to_dict()
    base.update(render_backend=backend, output_directory=str(root / "caption-jobs"))
    words = bridge_data()["verses"]["2:255"]["word_count"]
    dense = deepcopy(base)
    dense.update(
        cues=[
            {
                "cue_id": "kursi",
                "spans": [
                    {"surah": 2, "ayah": 255, "word_start": 1, "word_end": words}
                ],
            }
        ],
        profile={
            "id": "benchmark",
            "revision": "1",
            "approval": "approved",
            "provenance": {"purpose": "Offline preview benchmark"},
            "styles": {
                "arabic": {
                    "fit": "shrink",
                    "font_size": 36,
                    "min_font_size": 20,
                    "region": [0.05, 0.22, 0.95, 0.62],
                    "max_lines": 5,
                }
            },
        },
    )
    for case, data in (
        (
            "caption-titles",
            {**base, "titles": True, "quotations": True, "verse_numbers": True},
        ),
        ("caption-dense", dense),
    ):
        cache = CaptionRenderCache()
        for run in ("cold", "repeated", "color-edit"):
            chosen = deepcopy(data)
            if run == "color-edit":
                profile = chosen.setdefault(
                    "profile",
                    {
                        "id": "benchmark",
                        "revision": "1",
                        "approval": "approved",
                        "provenance": {"purpose": "Offline preview benchmark"},
                    },
                )
                profile.setdefault("styles", {}).setdefault("arabic", {})["color"] = (
                    "#EEEEEE"
                )
            start = time.perf_counter()
            response = execute_request(chosen, cache=cache).to_dict()
            elapsed = time.perf_counter() - start
            if response["status"] != "complete":
                raise RuntimeError(response)
            results.append(
                {
                    "case": case,
                    "run": run,
                    "total_s": elapsed,
                    "assets": len(response["assets"]),
                }
            )
            print(json.dumps(results[-1]), flush=True)
    return {"backend": backend, "runtime": runtime_identity(), "cases": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--backend", choices=("pillow", "imagemagick"), default="pillow"
    )
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    report = benchmark(args.output.resolve(), args.backend, args.config)
    (args.output / "benchmark.json").write_text(json.dumps(report, indent=2), "utf-8")
