"""Public API adapter example: source-aware current/cumulative states and a fade.

Run against an approved ordinary batch request, e.g.:
python examples/word_emphasis.py request.json --output ./word-example --unit 1
The caller supplies recitation timing; this example writes still endpoint frames.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from quran_image_generator.api import capabilities, execute_request
from quran_image_generator.word_emphasis import (
    compose_word_state,
    interpolate_word_states,
)


def example(
    request: dict[str, Any],
    output: Path,
    cue_index: int,
    unit_index: int,
    progress: float,
    asset_root: Path | None = None,
) -> dict[str, Any]:
    data = copy.deepcopy(request)
    backend = data.get("render_backend", "pillow")
    if not capabilities(backend)["word_emphasis"]["supported"]:
        raise ValueError("Install/select Pillow RAQM for source-word emphasis")
    data.setdefault("word_emphasis", {})
    # Obtain verified source groups before turning the consumer's timing into weights.
    for cue in data["cues"]:
        cue.pop("word_states", None)
    layout = execute_request(
        {**data, "operation": "layout"}, asset_root=asset_root
    ).to_dict()
    if layout["status"] != "complete":
        raise ValueError(layout.get("error") or layout["cues"])
    units = layout["cues"][cue_index]["word_emphasis"]["units"]
    chosen = units[unit_index]

    def selections(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "span_occurrence": m["span_occurrence"],
                "source_word": m["source_word"],
                "weight": 1,
            }
            for unit in selected
            for m in unit["members"]
        ]

    data["cues"][cue_index]["word_states"] = [
        {"state_id": "all"},
        {"state_id": "inactive", "default_weight": 0},
        {"state_id": "current", "default_weight": 0, "words": selections([chosen])},
        {
            "state_id": "cumulative",
            "default_weight": 0,
            "words": selections(units[: unit_index + 1]),
        },
    ]
    output.mkdir(parents=True, exist_ok=True)
    response = execute_request(
        {
            **data,
            "operation": "render_batch",
            "cropped": True,
            "output_directory": str(output.resolve()),
        },
        asset_root=asset_root,
    ).to_dict()
    if response["status"] != "complete":
        raise ValueError(response.get("error") or response["cues"])
    assert (
        response["cues"][cue_index]["word_emphasis"]["layout_id"]
        == layout["cues"][cue_index]["word_emphasis"]["layout_id"]
    )
    for state in ("all", "inactive", "current", "cumulative"):
        with compose_word_state(response, cue_index, state) as image:
            image.save(output / (state + ".png"))
    with (
        compose_word_state(response, cue_index, "inactive") as a,
        compose_word_state(response, cue_index, "current") as b,
        interpolate_word_states(a, b, progress) as frame,
    ):
        frame.save(output / "transition.png")
    # Retain this manifest and its immutable job directory while exports refer to it.
    (output / "response.json").write_text(
        json.dumps(response, indent=2), encoding="utf-8"
    )
    return response


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cue", type=int, default=0)
    parser.add_argument("--unit", type=int, default=0)
    parser.add_argument("--progress", type=float, default=0.5)
    args = parser.parse_args()
    result = example(
        json.loads(args.request.read_text(encoding="utf-8")),
        args.output,
        args.cue,
        args.unit,
        args.progress,
        args.request.resolve().parent,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "manifest": str(args.output.resolve() / "response.json"),
            }
        )
    )


if __name__ == "__main__":
    main()
