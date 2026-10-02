"""External caller example: installed public interfaces only."""

from pathlib import Path

from quran_image_generator.api import capabilities, execute_request
from quran_image_generator.references import SourceSpan
from quran_image_generator.requests import BatchRequest, CueRequest

info = capabilities()
if 1 not in info["schema_versions"] or not info["renderer_version"].startswith("0.2."):
    raise RuntimeError("Install compatible quran-image-generator 0.2.x")
batch = BatchRequest(
    "external-clip",
    (
        CueRequest(
            "first",
            (SourceSpan(31, 9, 1, 5),),
            metadata={"start_seconds": 0.4, "end_seconds": 3.4},
        ),
        CueRequest(
            "repeat",
            (SourceSpan(31, 9, 1, 5),),
            metadata={"start_seconds": 4, "end_seconds": 7},
        ),
        CueRequest("basmala", (SourceSpan(0, 0, 1, 4),)),
        CueRequest("verse-tail", (SourceSpan(39, 30, 4, 4),)),
    ),
    operation="render_batch",
    output_directory=str(Path("caption jobs").resolve()),
)
response = execute_request(batch.to_request()).to_dict()
if response["status"] != "complete":
    raise RuntimeError(response)
print(response["job_directory"])
