"""Render six authored references beside verified local burned-in source frames."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat

from quran_image_generator.api import execute_request


def image_difference(reference: Image.Image, candidate: Image.Image) -> dict:
    """Compare alpha and composites; invisible RGB must not skew similarity."""
    if (
        reference.mode != "RGBA"
        or candidate.mode != "RGBA"
        or reference.size != candidate.size
    ):
        raise ValueError("Compare equal-size RGBA images")
    reference_bounds = reference.getchannel("A").getbbox()
    candidate_bounds = candidate.getchannel("A").getbbox()
    if reference_bounds is None or candidate_bounds is None:
        raise ValueError("Visual fixtures must contain visible ink")
    region = tuple(
        min(a, b) if i < 2 else max(a, b)
        for i, (a, b) in enumerate(zip(reference_bounds, candidate_bounds, strict=True))
    )
    errors = []
    for background in ("black", "white"):
        left = Image.new("RGBA", reference.size, background)
        right = left.copy()
        left.alpha_composite(reference)
        right.alpha_composite(candidate)
        diff = ImageChops.difference(left.convert("RGB"), right.convert("RGB")).crop(
            region
        )
        errors.append(sum(ImageStat.Stat(diff).mean) / (3 * 255))
    alpha_diff = ImageChops.difference(
        reference.getchannel("A"), candidate.getchannel("A")
    ).crop(region)
    return {
        "bounds_drift": max(
            abs(a - b) for a, b in zip(reference_bounds, candidate_bounds, strict=True)
        ),
        "alpha_mean_error": ImageStat.Stat(alpha_diff).mean[0] / 255,
        "composite_mean_error": max(errors),
    }


def assert_image_matches(reference: Image.Image, candidate: Image.Image) -> None:
    measured = image_difference(reference, candidate)
    # Within a pinned raster runtime, allow minor antialiasing differences only.
    assert measured["bounds_drift"] <= 2, measured
    assert measured["alpha_mean_error"] <= 0.025, measured
    assert measured["composite_mean_error"] <= 0.025, measured


def composite_cue(result: dict, cue: dict, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    records = {asset["asset_id"]: asset for asset in result["assets"]}
    for asset_id in cue["asset_ids"]:
        record = records[asset_id]
        path = Path(result["job_directory"]) / record["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Caption asset checksum mismatch")
        with Image.open(path) as image:
            canvas.alpha_composite(image, tuple(record["offset"]))
    return canvas


def build_review(fixtures: Path, output: Path, media: Path | None, ffmpeg: str) -> None:
    data = json.loads(fixtures.read_text("utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGB", (640, 64 + 6 * 604), "#202124")
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 8), "SOURCE / BUNDLED PREVIEW - needs creator review", fill="white")
    draw.text(
        (12, 28),
        "Fonts, logo and translation edition unconfirmed; no timing approval.",
        fill="white",
    )
    reports = []
    for index, case in enumerate(data["cases"]):
        request = {
            **case["request"],
            "translation_dataset": data["translation_dataset"],
            "output_directory": str(output.resolve() / case["clip_id"]),
            "cropped": True,
        }
        result = execute_request(request).to_dict()
        if result["status"] != "needs_review":
            raise ValueError(f"Caption fixture failed: {result}")
        cue = result["cues"][0]
        composed = composite_cue(result, cue, (576, 1024))
        composed.save(output / f"{case['clip_id']}-overlay.png")
        preview = Image.new("RGBA", composed.size, "#343a46")
        preview.alpha_composite(composed)
        preview.thumbnail((320, 570))
        source = Image.new("RGB", (320, 570), "#151515")
        reference = {"status": "unavailable"}
        if media is not None:
            path = media / f"{case['clip_id']}.mp4"
            if hashlib.sha256(path.read_bytes()).hexdigest() != case["media_sha256"]:
                raise ValueError(f"Reference media changed: {case['clip_id']}")
            frame = output / f"{case['clip_id']}-source.png"
            subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    str(case["reference_seconds"]),
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-y",
                    str(frame),
                ],
                check=True,
            )
            with Image.open(frame) as image:
                image.thumbnail((320, 570))
                source.paste(image, (0, 0))
            reference = {
                "status": "verified_local",
                "frame_sha256": hashlib.sha256(frame.read_bytes()).hexdigest(),
            }
        y = 64 + index * 604
        draw.text(
            (8, y),
            f"{case['clip_id']} / source at {case['reference_seconds']}s",
            fill="white",
        )
        draw.text((328, y), "Bundled preview - logo unavailable", fill="white")
        sheet.paste(source, (0, y + 24))
        sheet.paste(preview.convert("RGB"), (320, y + 24))
        reports.append(
            {
                "clip_id": case["clip_id"],
                "approval": "needs_review",
                "source": reference,
                "runtime": result["runtime"],
                "profile": result["profile"],
                "expected": case["expected"][0],
                "asset_sha256": [asset["sha256"] for asset in result["assets"]],
            }
        )
    sheet.save(output / "contact-sheet.jpg", quality=92)
    (output / "review.json").write_text(
        json.dumps(
            {"approval": "needs_review", "cases": reports}, ensure_ascii=False, indent=2
        ),
        "utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "tests/fixtures/captions/six-references.json",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--media-directory", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    build_review(args.fixtures, args.output_dir, args.media_directory, args.ffmpeg)
