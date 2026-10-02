"""Review discovered creator fonts against six verified local source videos."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

from caption_review import composite_cue
from PIL import Image, ImageDraw

from quran_image_generator.api import execute_request
from quran_image_generator.bindings import BindingDataset
from quran_image_generator.creator_assets import (
    matched_creator_configuration,
    matched_creator_titles,
)


def build_review(
    fonts: Path, latin: Path, media: Path, output: Path, ffmpeg: str
) -> None:
    config = matched_creator_configuration(fonts, latin)
    fixtures = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "tests/fixtures/captions/six-references.json"
        ).read_text("utf-8")
    )
    dataset = BindingDataset.from_dict(fixtures["translation_dataset"])
    # These explicit line breaks are transcribed from the two-second references.
    line_breaks = {
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
            replace(b, segments=line_breaks[b.binding_id])
            if b.binding_id in line_breaks
            else b
            for b in dataset.bindings
        ),
    )
    output.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGB", (1152, 48 + 6 * 294), "#202124")
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 8), "SOURCE / CREATOR FONT PREVIEW - needs review", fill="white")
    draw.text(
        (12, 26),
        "Original fonts and glyphs; authored English fixture, no timing/translation-edition approval.",
        fill="white",
    )
    reports = []
    for index, case in enumerate(fixtures["cases"]):
        clip = case["clip_id"]
        video = media / f"{clip}.mp4"
        if hashlib.sha256(video.read_bytes()).hexdigest() != case["media_sha256"]:
            raise ValueError(f"Source media checksum changed: {clip}")
        cue = dict(case["request"]["cues"][0])
        cue.update(matched_creator_titles(cue["spans"][0]["surah"]))
        request = {
            **case["request"],
            **config,
            "cues": [cue],
            "translation_dataset": dataset.to_dict(),
            "cropped": True,
            "output_directory": str(output.resolve() / clip),
        }
        result = execute_request(request).to_dict()
        if result["status"] != "needs_review":
            raise ValueError(f"Creator caption failed: {result}")
        overlay = composite_cue(result, result["cues"][0], (576, 1024))
        overlay.save(output / f"{clip}-overlay.png")
        preview = Image.new("RGBA", overlay.size, "#202124")
        preview.alpha_composite(overlay)
        preview.save(output / f"{clip}-preview.png")
        frame = output / f"{clip}-source.png"
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                str(case["reference_seconds"]),
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-y",
                str(frame),
            ],
            check=True,
        )
        y = 48 + index * 294
        draw.text((10, y), clip + " / source at 2s", fill="white")
        draw.text((588, y), "Matched fonts on a blank background", fill="white")
        with Image.open(frame) as source:
            for x, image in ((0, source), (576, preview)):
                offset = 20
                for box in ((0, 135, 576, 205), (0, 470, 576, 590), (0, 885, 576, 960)):
                    sheet.paste(image.crop(box).convert("RGB"), (x, y + offset))
                    offset += box[3] - box[1]
        reports.append(
            {
                "clip_id": clip,
                "approval": "needs_review",
                "source_media_sha256": case["media_sha256"],
                "source_frame_sha256": hashlib.sha256(frame.read_bytes()).hexdigest(),
                "runtime": result["runtime"],
                "arabic": result["cues"][0]["arabic"],
                "layers": result["cues"][0]["layers"],
                "asset_sha256": [a["sha256"] for a in result["assets"]],
            }
        )
    sheet.save(output / "creator-font-comparison.jpg", quality=95)
    (output / "creator-options.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), "utf-8"
    )
    (output / "review.json").write_text(
        json.dumps(
            {
                "approval": "needs_review",
                "profile": config["profile"],
                "cases": reports,
            },
            ensure_ascii=False,
            indent=2,
        ),
        "utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--creator-font-directory", type=Path, required=True)
    parser.add_argument("--latin-font", type=Path, required=True)
    parser.add_argument("--media-directory", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    build_review(
        args.creator_font_directory,
        args.latin_font,
        args.media_directory,
        args.output_dir,
        args.ffmpeg,
    )
