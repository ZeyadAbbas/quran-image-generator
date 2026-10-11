"""Reproducible static-asset budget for authored 1/10-minute caption plans."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from quran_image_generator.api import execute_request, runtime_identity
from quran_image_generator.references import CorpusIdentity


def peak_rss() -> int:
    if os.name != "nt":
        import resource

        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak_working_set",
                "working_set",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "pagefile",
                "peak_pagefile",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not ctypes.windll.psapi.GetProcessMemoryInfo(
        ctypes.c_void_p(-1), ctypes.byref(counters), counters.cb
    ):
        raise OSError("Cannot read native process memory")
    return int(counters.peak_working_set)


def benchmark(root: Path) -> dict[str, object]:
    cases = []
    for minutes, count in ((1, 15), (10, 150)):
        spans = [(31, 9, 1, 5), (31, 11, 1, 3), (39, 30, 4, 4)]
        cues = [
            {
                "cue_id": f"c{i:04}",
                "spans": [
                    dict(
                        zip(
                            ("surah", "ayah", "word_start", "word_end"),
                            spans[i % 3],
                            strict=True,
                        )
                    )
                ],
                "metadata": {"start_seconds": i * 4, "end_seconds": (i + 1) * 4},
            }
            for i in range(count)
        ]
        request = {
            "schema_version": 1,
            "request_id": f"authored-{minutes}m",
            "operation": "render_batch",
            "source_corpus": asdict(CorpusIdentity()),
            "canvas": {"width": 576, "height": 1024},
            "titles": True,
            "cues": cues,
            "output_directory": str(root / f"{minutes}m jobs"),
            "asset_cache_directory": str(root / f"{minutes}m cache"),
        }
        timings = []
        for label in ("cold", "warm"):
            started = time.perf_counter()
            result = execute_request(request).to_dict()
            if result["status"] != "complete":
                raise RuntimeError(json.dumps(result))
            timings.append(
                {
                    "run": label,
                    "seconds": round(time.perf_counter() - started, 3),
                    "assets": len(result["assets"]),
                    "peak_process_rss_bytes": peak_rss(),
                }
            )
        cases.append({"minutes": minutes, "occurrences": count, "results": timings})
    return {
        "runtime": runtime_identity(),
        "fixture": "authored plans, 4-second cues, 3 Arabic states and persistent titles; no video-frame rendering",
        "cases": cases,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result = benchmark(args.output)
    (args.output / "benchmark.json").write_text(json.dumps(result, indent=2), "utf-8")
    print(json.dumps(result, indent=2))
