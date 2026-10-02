"""Native Caption Studio smoke from an installed wheel outside the checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from quran_image_generator.api import capabilities, execute_request
from quran_image_generator.caption_editor import CaptionDocument, compose_caption
from quran_image_generator.caption_gui import CaptionStudio


def smoke(output: Path) -> None:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    root.withdraw()
    app = CaptionStudio(root)
    try:
        app._vars["output_directory"].set(str(output / "layers"))
        app._vars["titles"].set(True)
        app._vars["cropped"].set(True)
        app._vars["start_seconds"].set("0.4")
        app._vars["end_seconds"].set("3.4")
        app._styles["font_size"].set("28.25")
        app._styles["horizontal_scale"].set("1.1")
        app._styles["outline_width"].set("0.3")
        app._duplicate()
        app._vars["profile_approval"].set("approved")
        request_file = output / "native request.json"
        with patch(
            "quran_image_generator.caption_gui.filedialog.asksaveasfilename",
            return_value=str(request_file),
        ):
            assert app.save_request()
        loaded = CaptionDocument.load(request_file)
        app._start("export")
        deadline = time.monotonic() + 60
        while app._worker.busy:
            root.update()
            time.sleep(0.01)
            assert time.monotonic() < deadline, "Caption Studio worker timed out"
        if app._poll_id:
            root.after_cancel(app._poll_id)
        app._poll()
        assert app._response and app._response["status"] == "complete", (
            app._status.get()
        )
        replay = execute_request(loaded.request()).to_dict()
        assert replay["status"] == "complete"
        assert [a["sha256"] for a in replay["assets"]] == [
            a["sha256"] for a in app._response["assets"]
        ]
        png = output / "native combined.png"
        with patch(
            "quran_image_generator.caption_gui.filedialog.asksaveasfilename",
            return_value=str(png),
        ):
            app.save_png()
        with Image.open(png) as image:
            assert image.size == (576, 1024) and image.getpixel((0, 0))[3] == 0
            assert image.tobytes() == compose_caption(replay, 1, image.size).tobytes()
        (output / "caption-gui-smoke-summary.json").write_text(
            json.dumps(
                {
                    "renderer_version": capabilities()["renderer_version"],
                    "style_controls": len(app._styles),
                    "captions": len(replay["cues"]),
                    "replay_checksums_equal": True,
                    "combined_sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
                },
                indent=2,
            ),
            "utf-8",
        )
    finally:
        app.close(discard=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    smoke(parser.parse_args().output_dir)
