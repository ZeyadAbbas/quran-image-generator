"""Public-API/JSON smoke suitable for an independent installed wheel."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from quran_image_generator.api import capabilities, execute_request
from quran_image_generator.bindings import (
    BindingDataset,
    PhraseBinding,
    TranslationSource,
    text_hash,
)
from quran_image_generator.excerpts import ExcerptRequest, select_excerpt
from quran_image_generator.references import CorpusIdentity, SourceSpan
from quran_image_generator.snapshots import SnapshotStore


def smoke(output: Path) -> None:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    assert 1 in capabilities()["schema_versions"]
    assert capabilities()["renderer_version"] == "0.3.0"
    spans = (SourceSpan(31, 9, 1, 5),)
    excerpt = select_excerpt(ExcerptRequest("phrase", spans))
    source = TranslationSource(
        "local",
        "authored-install-fixture",
        "1",
        "Fixture author",
        "test-only",
        "Authored smoke text, not creator source identification",
    )
    english = "staying there forever. Allah's promise is true."
    binding = PhraseBinding(
        "phrase",
        "1",
        spans,
        text_hash(excerpt.text),
        english,
        text_hash(english),
        (english,),
        "approved",
        "Authored installation fixture",
        source_identity_sha256=source.identity_sha256,
    )
    dataset = BindingDataset(source, CorpusIdentity(), (binding,))
    snapshot = SnapshotStore(output / "offline translation cache")
    digest = snapshot.import_dataset(dataset)
    request = {
        "schema_version": 1,
        "request_id": "installed smoke",
        "operation": "render_batch",
        "source_corpus": asdict(CorpusIdentity()),
        "canvas": {"width": 576, "height": 1024},
        "titles": True,
        "quotations": True,
        "verse_numbers": True,
        "output_directory": str(output),
        "translation_snapshot": {
            "directory": str(snapshot.directory),
            "sha256": digest,
        },
        "cues": [
            {
                "cue_id": key,
                "spans": [asdict(span) for span in spans],
                "translation_policy": "required",
                "translation_binding_id": "phrase",
            }
            for key in ("occurrence 1", "repeat 2")
        ],
    }
    preflight = execute_request({**request, "operation": "preflight"}).to_dict()
    assert preflight["status"] == "complete", preflight
    python_result = execute_request(request).to_dict()
    path = output / "request with spaces.json"
    path.write_text(json.dumps(request, ensure_ascii=False), "utf-8")
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "quran_image_generator.machine_cli",
            "--request",
            str(path),
        ],
        cwd=output,
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    machine = json.loads(process.stdout)
    assert not process.stderr and machine["status"] == "complete"
    assert machine["assets"] == python_result["assets"]
    assert machine["cues"] == python_result["cues"]
    for asset in machine["assets"]:
        png = Path(machine["job_directory"]) / asset["path"]
        assert hashlib.sha256(png.read_bytes()).hexdigest() == asset["sha256"]
        with Image.open(png) as image:
            assert image.mode == "RGBA" and image.getpixel((0, 0))[3] == 0
    assert "tkinter" not in sys.modules and "instagrapi" not in sys.modules
    (output / "caption-smoke-summary.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "assets": len(machine["assets"]),
                "schema_version": 1,
                "renderer_version": "0.3.0",
            }
        ),
        "utf-8",
    )
    print("Installed Python/JSON caption smoke passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    smoke(parser.parse_args().output_dir)
