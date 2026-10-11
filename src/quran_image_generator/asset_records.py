"""Transport-neutral rendered asset metadata."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OverlayAsset:
    sha256: str
    width: int
    height: int
    offset: tuple[int, int]
    bounds: tuple[int, int, int, int] | None
    alpha_mode: str = "straight"
    color_space: str = "sRGB"
