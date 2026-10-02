"""Non-interactive UTF-8 JSON adapter for the versioned caption API."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .api import MAX_REQUEST_BYTES, execute_request, failure_response
from .batching import BatchProgress
from .references import ReferenceError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--request", default="-", help="UTF-8 JSON file, or - for stdin"
    )
    parser.add_argument(
        "--asset-root",
        type=Path,
        help="Explicit base directory for relative input/output paths",
    )
    parser.add_argument("--capabilities", action="store_true")
    parser.add_argument(
        "--progress", action="store_true", help="Progress JSON lines on stderr"
    )
    parser.add_argument(
        "--deadline",
        type=float,
        help="Maximum batch seconds; checked between cues/layers",
    )
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        if args.capabilities:
            value = {
                "schema_version": 1,
                "request_id": "capabilities",
                "operation": "capabilities",
            }
            root = args.asset_root
        else:
            if args.request == "-":
                raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
                root = args.asset_root
            else:
                path = Path(args.request).resolve()
                with path.open("rb") as stream:
                    raw = stream.read(MAX_REQUEST_BYTES + 1)
                root = args.asset_root or path.parent
            if len(raw) > MAX_REQUEST_BYTES:
                raise ReferenceError("invalid_request", "Request exceeds 8 MB")
            value = json.loads(
                raw.decode("utf-8-sig"), object_pairs_hook=_unique_fields
            )

        def report(event: BatchProgress) -> None:
            print(json.dumps(asdict(event), ensure_ascii=True), file=sys.stderr)

        response = execute_request(
            value,
            asset_root=root,
            progress=report if args.progress else None,
            deadline_seconds=args.deadline,
        )
    except (
        UnicodeError,
        json.JSONDecodeError,
        ReferenceError,
        OSError,
        RecursionError,
    ) as error:
        response = failure_response(
            None,
            error
            if isinstance(error, ReferenceError)
            else ReferenceError("invalid_request", "Cannot read UTF-8 JSON request"),
        )
    except KeyboardInterrupt:
        response = failure_response(
            None, ReferenceError("cancelled", "Render cancelled")
        )
    json.dump(response.to_dict(), sys.stdout, ensure_ascii=False, allow_nan=False)
    sys.stdout.write("\n")
    return 0 if response.payload["status"] in ("complete", "needs_review") else 2


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReferenceError("invalid_request", "Duplicate JSON object field")
        result[key] = value
    return result


if __name__ == "__main__":
    raise SystemExit(main())
