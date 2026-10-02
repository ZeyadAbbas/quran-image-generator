"""Bounded batch control and immutable, verified on-disk asset reuse."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .asset_records import OverlayAsset
from .references import ReferenceError
from .snapshots import canonical_bytes


@dataclass(frozen=True, slots=True)
class BatchProgress:
    phase: str
    completed: int
    total: int
    cue_id: str | None = None


class BatchControl:
    def __init__(
        self,
        seconds: float,
        cancelled: Callable[[], bool] | None,
        progress: Callable[[BatchProgress], None] | None,
    ) -> None:
        if not 0 < seconds <= 3600:
            raise ReferenceError(
                "invalid_request", "Batch deadline must be in 0..3600 seconds"
            )
        self.deadline = time.monotonic() + seconds
        self.cancelled, self.progress = cancelled, progress

    def checkpoint(
        self, phase: str, completed: int, total: int, cue_id: str | None = None
    ) -> None:
        if self.cancelled and self.cancelled():
            raise ReferenceError("cancelled", "Batch cancelled between cues/layers")
        if time.monotonic() >= self.deadline:
            raise ReferenceError("deadline_exceeded", "Batch deadline exceeded")
        if self.progress:
            self.progress(BatchProgress(phase, completed, total, cue_id))


def _atomic_bytes(path: Path, raw: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = stream.name
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


class AssetCache:
    """Each call owns its renderer; concurrent cache publication is atomic."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def restore(self, asset_id: str, destination: Path) -> OverlayAsset | None:
        if not re.fullmatch(r"[0-9a-f]{64}", asset_id):
            raise ReferenceError("corrupt_asset_cache", "Invalid cache key")
        metadata = self.directory / f"{asset_id}.json"
        if not metadata.exists():
            return None
        try:
            if metadata.stat().st_size > 4096:
                raise ValueError("oversized metadata")
            data: dict[str, Any] = json.loads(metadata.read_bytes())
            image = self.directory / f"{asset_id}.png"
            if (
                image.stat().st_size > 64_000_000
                or hashlib.sha256(image.read_bytes()).hexdigest() != data["sha256"]
            ):
                raise ValueError("checksum")
            data["offset"] = tuple(data["offset"])
            if data["bounds"] is not None:
                data["bounds"] = tuple(data["bounds"])
            asset = OverlayAsset(**data)
            shutil.copyfile(image, destination)
            return asset
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ReferenceError(
                "corrupt_asset_cache",
                "Cached asset is missing/corrupt; explicitly remove that cache entry",
            ) from error

    def store(self, asset_id: str, path: Path, asset: OverlayAsset) -> None:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != asset.sha256:
            raise ReferenceError(
                "output_io", "Rendered asset changed before cache publication"
            )
        _atomic_bytes(self.directory / f"{asset_id}.png", raw)
        _atomic_bytes(
            self.directory / f"{asset_id}.json", canonical_bytes(asdict(asset))
        )
