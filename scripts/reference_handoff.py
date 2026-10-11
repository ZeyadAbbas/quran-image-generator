"""Build local sample requests and verify matched layers from an installed renderer."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageStat

from quran_image_generator.api import execute_request
from quran_image_generator.bindings import BindingDataset

if __package__:
    from .caption_review import assert_image_matches, image_difference
    from .reference_caption_options import (
        matched_creator_configuration,
        matched_creator_titles,
    )
else:
    from caption_review import assert_image_matches, image_difference
    from reference_caption_options import (
        matched_creator_configuration,
        matched_creator_titles,
    )


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests/fixtures/captions/matched"
ROLES = ("arabic", "translation", "arabic_title", "latin_title", "logo")


def reference_requests(fonts: Path, latin: Path, output: Path) -> list[dict]:
    fixtures = json.loads(
        (ROOT / "tests/fixtures/captions/six-references.json").read_text("utf-8")
    )
    dataset = BindingDataset.from_dict(fixtures["translation_dataset"])
    breaks = {
        "39:29:1-7": (
            "Allah sets forth the parable of a slave owned by",
            "several quarrelsome masters,",
        ),
        "5:72:1-10": (
            'Those who say, "Allah is the Messiah, son of Mary,"',
            "have certainly fallen into disbelief.",
        ),
    }
    dataset = replace(
        dataset,
        bindings=tuple(
            replace(b, segments=breaks[b.binding_id]) if b.binding_id in breaks else b
            for b in dataset.bindings
        ),
    )
    config = matched_creator_configuration(fonts, latin)
    requests = []
    for case in fixtures["cases"]:
        request = {
            **copy.deepcopy(case["request"]),
            **copy.deepcopy(config),
            "cropped": True,
            "translation_dataset": dataset.to_dict(),
            "output_directory": str((output / "jobs" / case["clip_id"]).resolve()),
            "metadata": {
                "clip_id": case["clip_id"],
                "source_media_sha256": case["media_sha256"],
                "purpose": "Authored style/fit fixture; no production timing/translation approval",
            },
        }
        for cue in request["cues"]:
            cue.update(matched_creator_titles(cue["spans"][0]["surah"]))
        requests.append(request)
    return requests


def full_layer(
    result: dict, cue: dict, role: str, size: tuple[int, int]
) -> Image.Image:
    records = {a["asset_id"]: a for a in result["assets"]}
    matching = [
        records[key] for key in cue["asset_ids"] if role in records[key]["roles"]
    ]
    if len(matching) != 1:
        raise AssertionError(f"Missing/duplicate required reference layer: {role}")
    record = matching[0]
    path = Path(result["job_directory"]) / record["path"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise AssertionError(f"Layer asset checksum mismatch: {role}")
    canvas = Image.new("RGBA", size)
    with Image.open(path) as image:
        if image.mode != "RGBA" or image.size != (record["width"], record["height"]):
            raise AssertionError(f"Layer format/dimensions mismatch: {role}")
        canvas.alpha_composite(image, tuple(record["offset"]))
    if list(canvas.getchannel("A").getbbox() or ()) != record["bounds"]:
        raise AssertionError(f"Layer offset/ink bounds mismatch: {role}")
    return canvas


def assert_layer_matches(
    reference: Image.Image, candidate: Image.Image, *, pixel: bool
) -> dict:
    """Every layer gets a separate gate, so large verse ink cannot hide a lost logo."""
    if (
        reference.getchannel("A").getbbox() is None
        or candidate.getchannel("A").getbbox() is None
    ):
        raise AssertionError("Required layer has no visible ink")
    measured = image_difference(reference, candidate)
    if pixel:
        assert_image_matches(reference, candidate)
    else:
        assert measured["bounds_drift"] <= 4, measured
        before = ImageStat.Stat(reference.getchannel("A")).sum[0]
        after = ImageStat.Stat(candidate.getchannel("A")).sum[0]
        assert 0.9 <= after / before <= 1.1, measured
    return measured


def _signature(request: dict) -> str:
    def portable(value):
        if isinstance(value, dict):
            return {
                k: portable(v)
                for k, v in value.items()
                if k not in ("path", "output_directory")
            }
        if isinstance(value, (list, tuple)):
            return [portable(v) for v in value]
        return value

    return hashlib.sha256(
        json.dumps(portable(request), ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def verify_handoff(
    fonts: Path,
    latin: Path,
    output: Path,
    *,
    baseline: Path = BASELINE,
    capture: bool = False,
    machine: bool = True,
) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if capture:
        baseline.mkdir(parents=True, exist_ok=True)
        expected = None
    else:
        expected = json.loads((baseline / "baseline.json").read_text("utf-8"))
    reports = []
    matrix = []
    requests = reference_requests(fonts, latin, output)
    for request in requests:
        clip = request["metadata"]["clip_id"]
        path = output / f"{clip}-request.json"
        path.write_text(json.dumps(request, ensure_ascii=False, indent=2), "utf-8")
        for width, height in ((576, 1024), (1080, 1920)):
            layout = execute_request(
                {
                    **request,
                    "operation": "layout",
                    "canvas": {"width": width, "height": height},
                }
            ).to_dict()
            assert layout["status"] == "needs_review", layout
            assert all(cue["status"] == "needs_review" for cue in layout["cues"]), (
                layout
            )
            matrix.append(
                {
                    "clip_id": clip,
                    "canvas": {"width": width, "height": height},
                    "cues": layout["cues"],
                }
            )
        first = {**request, "cues": request["cues"][:1]}
        result = execute_request(first).to_dict()
        assert result["status"] == "needs_review", result
        if machine:
            first_path = output / f"{clip}-first-cue.json"
            first_path.write_text(
                json.dumps(first, ensure_ascii=False, indent=2), "utf-8"
            )
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "quran_image_generator.machine_cli",
                    "--request",
                    str(first_path),
                ],
                cwd=output,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            assert process.returncode == 0, (process.stdout, process.stderr)
            returned = json.loads(process.stdout)
            assert not process.stderr, process.stderr
            assert returned["assets"] == result["assets"], "Python/JSON assets differ"
            assert (
                returned["cues"] == result["cues"]
                and returned["runtime"] == result["runtime"]
            )
        old = (
            None
            if expected is None
            else next(c for c in expected["cases"] if c["clip_id"] == clip)
        )
        signature = _signature(first)
        if old is not None:
            assert signature == old["request_sha256"], (
                "Reference text/style/font identity changed"
            )
        layers = []
        for role in ROLES:
            canvas = full_layer(result, result["cues"][0], role, (576, 1024))
            bounds = canvas.getchannel("A").getbbox()
            assert bounds is not None and canvas.getpixel((0, 0))[3] == 0
            filename = f"{clip}-{role}.png"
            if capture:
                canvas.crop(bounds).save(baseline / filename)
                record = {
                    "role": role,
                    "path": filename,
                    "bounds": list(bounds),
                    "sha256": hashlib.sha256(
                        (baseline / filename).read_bytes()
                    ).hexdigest(),
                }
            else:
                record = next(layer for layer in old["layers"] if layer["role"] == role)
                baseline_path = baseline / record["path"]
                assert (
                    hashlib.sha256(baseline_path.read_bytes()).hexdigest()
                    == record["sha256"]
                )
                reference = Image.new("RGBA", canvas.size)
                with Image.open(baseline_path) as crop:
                    reference.alpha_composite(crop, tuple(record["bounds"][:2]))
                pixel = expected["runtime"] == result["runtime"]
                difference = assert_layer_matches(reference, canvas, pixel=pixel)
                record = {
                    **record,
                    "comparison": "pixels" if pixel else "structural",
                    "difference": difference,
                }
            layers.append(record)
        reports.append(
            {
                "clip_id": clip,
                "request_sha256": signature,
                "source_media_sha256": request["metadata"]["source_media_sha256"],
                "arabic": result["cues"][0]["arabic"],
                "layers": layers,
            }
        )
    report = {
        "status": "passed",
        "approval": "needs_review",
        "runtime": result["runtime"],
        "schema_version": 1,
        "description": "Measured technical baseline; no final visual, timing or translation-edition approval",
        "python_json_parity": machine,
        "caption_layouts": sum(len(item["cues"]) for item in matrix),
        "cases": reports,
    }
    if capture:
        (baseline / "baseline.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), "utf-8"
        )
    (output / "regression-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), "utf-8"
    )
    (output / "layout-matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2), "utf-8"
    )
    # The exported document remains navigable outside the repository.
    document = (ROOT / "docs/quranscribe-handoff.md").read_text("utf-8")

    def released_link(match):
        target = match.group(1)
        if ":" in target or target.startswith("#"):
            return match.group(0)
        relative = (ROOT / "docs" / target).resolve().relative_to(ROOT)
        return (
            "](https://github.com/ZeyadAbbas/quran-image-generator/blob/v0.3.3/"
            + quote(relative.as_posix())
            + ")"
        )

    (output / "QURANSCRIBE-HANDOFF.md").write_text(
        re.sub(r"\]\(([^)]+)\)", released_link, document), "utf-8"
    )
    demo = copy.deepcopy(requests[0])
    demo["cues"] = demo["cues"][:1]
    repeated = copy.deepcopy(demo["cues"][0])
    repeated["cue_id"] = "reference-repeat-example"
    demo["cues"].append(repeated)
    (output / "reference-request.json").write_text(
        json.dumps(demo, ensure_ascii=False, indent=2), "utf-8"
    )
    options = {
        key: demo[key]
        for key in (
            "assets",
            "profile",
            "titles",
            "quotations",
            "verse_numbers",
            "cropped",
        )
    }
    (output / "reference-style.json").write_text(
        json.dumps(options, ensure_ascii=False, indent=2), "utf-8"
    )
    print(
        f"Verified {len(reports)} references, {report['caption_layouts']} layouts and {len(reports) * len(ROLES)} separate layers"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-directory", type=Path, required=True)
    parser.add_argument("--latin-font", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument(
        "--capture-baseline",
        action="store_true",
        help="Explicitly create a technical baseline for review; never run automatically",
    )
    args = parser.parse_args()
    verify_handoff(
        args.font_directory,
        args.latin_font,
        args.output_dir,
        baseline=args.baseline,
        capture=args.capture_baseline,
    )
