"""Renderer selection and optional Windows complex-text library discovery."""

from __future__ import annotations

import ctypes
import hashlib
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Literal

Backend = Literal["pillow", "imagemagick"]
_backend: ContextVar[str] = ContextVar("qig_render_backend", default="auto")
_dll_handles: list[object] = []
FRIBIDI_SHA256 = ""


def _load_windows_fribidi() -> None:
    """Load a caller-installed DLL before Pillow initializes its RAQM shim.

    No native files are downloaded, copied, or installed at runtime. A standalone
    FriBiDi DLL can live beside the venv executable or in PILLOW_FRIBIDI_DLL.
    """
    global FRIBIDI_SHA256
    if sys.platform != "win32":
        return
    explicit = os.environ.get("PILLOW_FRIBIDI_DLL", "")
    directories = [Path(sys.prefix) / "Scripts", Path(sys.executable).parent]
    candidates = ([Path(explicit)] if explicit else []) + [
        directory / name
        for directory in directories
        for name in ("fribidi.dll", "fribidi-0.dll", "libfribidi-0.dll")
    ]
    for selected in candidates:
        if selected.is_file():
            try:
                _dll_handles.append(os.add_dll_directory(str(selected.parent)))
                _dll_handles.append(ctypes.CDLL(str(selected)))
                FRIBIDI_SHA256 = hashlib.sha256(selected.read_bytes()).hexdigest()
                return
            except OSError:
                continue


_load_windows_fribidi()


def selected_backend() -> str:
    return _backend.get()


@contextmanager
def using_backend(backend: str) -> Iterator[None]:
    if backend not in ("pillow", "imagemagick"):
        from .references import ReferenceError

        raise ReferenceError(
            "invalid_request",
            "Render backend must be pillow or imagemagick",
            details={"field": "render_backend"},
        )
    token = _backend.set(backend)
    try:
        yield
    finally:
        _backend.reset(token)


def require_pillow_shaping() -> None:
    from PIL import features

    if not features.check_feature("raqm"):
        from .references import ReferenceError

        raise ReferenceError(
            "missing_shaping",
            "Pillow rendering requires RAQM Arabic shaping. On Windows install "
            "fribidi.dll beside the virtual environment's Python executable or set "
            "PILLOW_FRIBIDI_DLL before starting Python. Alternatively select the "
            "imagemagick render backend.",
            details={"field": "render_backend", "path": "/render_backend", "backend": "pillow"},
        )
