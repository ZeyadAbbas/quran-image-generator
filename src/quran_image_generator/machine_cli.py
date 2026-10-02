"""Non-interactive UTF-8 JSON adapter for the versioned caption API."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .api import MAX_REQUEST_BYTES, execute_request, failure_response
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
            value = json.loads(raw.decode("utf-8-sig"))
        response = execute_request(value, asset_root=root)
    except (UnicodeError, json.JSONDecodeError, ReferenceError, OSError) as error:
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


if __name__ == "__main__":
    raise SystemExit(main())
