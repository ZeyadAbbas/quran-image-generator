"""Application orchestration and concrete service composition."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from .layout import build_layout
from .models import GenerationRequest, GenerationResult, Passage
from .settings import Settings


def _output_path(passage: Passage, output_directory: Path) -> Path:
    first_number = passage.verses[0].number
    last_number = passage.verses[-1].number
    filename = f"{passage.chapter_name} {first_number}"
    if len(passage.verses) > 1:
        filename += f" - {last_number}.png"
    else:
        filename += ".png"
    return output_directory / filename


def _open_image(path: Path) -> None:
    resolved = str(path.resolve())
    if sys.platform == "win32":
        os.startfile(resolved)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", resolved])
    else:
        subprocess.Popen(["xdg-open", resolved])


class QuranImageGenerator:
    """Coordinate content, layout, rendering, and local output actions."""

    def __init__(
        self,
        settings: Settings,
        content_client: Any,
        measurer: Any,
        renderer: Any,
        *,
        image_opener: Callable[[Path], None] = _open_image,
        layout_builder: Callable[..., Any] = build_layout,
    ) -> None:
        self._settings = settings
        self._content_client = content_client
        self._measurer = measurer
        self._renderer = renderer
        self._image_opener = image_opener
        self._layout_builder = layout_builder

    def generate(
        self,
        request: GenerationRequest,
        *,
        open_output: bool = False,
    ) -> GenerationResult:
        runtime_settings = self._settings
        if self._settings.translations:
            resources = self._content_client.resolve_translations(
                tuple(
                    translation.selector for translation in self._settings.translations
                )
            )
            runtime_settings = replace(
                self._settings,
                translations=tuple(
                    translation.resolve(resource)
                    for translation, resource in zip(
                        self._settings.translations, resources, strict=True
                    )
                ),
            )
        resource_ids = tuple(
            translation.resource_id for translation in runtime_settings.translations
        )
        passage = self._content_client.fetch_passage(request, resource_ids)
        if not passage.verses:
            return GenerationResult(path=None, passage=passage)

        image_layout = self._layout_builder(passage, runtime_settings, self._measurer)
        destination = _output_path(passage, runtime_settings.output_path)
        rendered_path = Path(
            self._renderer.render(image_layout, runtime_settings, destination)
        )
        result = GenerationResult(path=rendered_path, passage=passage)
        print("\nImage Created.\n")

        if open_output:
            self._image_opener(rendered_path)
        return result


def build_generator(
    settings: Settings, *, content_client: Any | None = None
) -> QuranImageGenerator:
    """Construct the concrete command-line application without doing I/O."""

    from .content import QuranContentClient
    from .rendering import WandImageRenderer, WandTextMeasurer

    return QuranImageGenerator(
        settings=settings,
        content_client=(
            QuranContentClient.from_environment()
            if content_client is None
            else content_client
        ),
        measurer=WandTextMeasurer(),
        renderer=WandImageRenderer(),
    )
