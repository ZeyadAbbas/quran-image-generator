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


def default_output_path(passage: Passage, output_directory: Path) -> Path:
    """Return the normal destination for a passage without creating it."""

    first_number = passage.verses[0].number
    last_number = passage.verses[-1].number
    filename = f"{passage.chapter_name} {first_number}"
    if len(passage.verses) > 1:
        filename += f" - {last_number}.png"
    else:
        filename += ".png"
    return output_directory / filename


def open_output(path: Path) -> None:
    """Open an image with the platform's default viewer."""

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
        image_opener: Callable[[Path], None] = open_output,
        layout_builder: Callable[..., Any] = build_layout,
    ) -> None:
        self._settings = settings
        self._content_client = content_client
        self._measurer = measurer
        self._renderer = renderer
        self._image_opener = image_opener
        self._layout_builder = layout_builder

    def resolve_settings(self, settings: Settings | None = None) -> Settings:
        """Resolve translation selectors without fetching or rendering verses."""

        selected_settings = self._settings if settings is None else settings
        runtime_settings = selected_settings
        if selected_settings.translations:
            resources = self._content_client.resolve_translations(
                tuple(
                    translation.selector for translation in selected_settings.translations
                )
            )
            runtime_settings = replace(
                selected_settings,
                translations=tuple(
                    translation.resolve(resource)
                    for translation, resource in zip(
                        selected_settings.translations, resources, strict=True
                    )
                ),
            )
        return runtime_settings

    def fetch_passage(
        self,
        request: GenerationRequest,
        settings: Settings | None = None,
    ) -> tuple[Settings, Passage]:
        """Resolve settings and fetch content, leaving rendering to the caller."""

        runtime_settings = self.resolve_settings(settings)
        resource_ids = tuple(
            translation.resource_id for translation in runtime_settings.translations
        )
        passage = self._content_client.fetch_passage(request, resource_ids)
        return runtime_settings, passage

    def render_passage(
        self,
        passage: Passage,
        settings: Settings,
        *,
        destination: Path | None = None,
    ) -> GenerationResult:
        """Render already-fetched content with the shared layout and renderer."""

        if not passage.verses:
            return GenerationResult(path=None, passage=passage)

        image_layout = self._layout_builder(passage, settings, self._measurer)
        if destination is None:
            destination = default_output_path(passage, settings.output_path)
        rendered_path = Path(
            self._renderer.render(image_layout, settings, destination)
        )
        return GenerationResult(path=rendered_path, passage=passage)

    def generate(
        self,
        request: GenerationRequest,
        *,
        open_output: bool = False,
    ) -> GenerationResult:
        runtime_settings, passage = self.fetch_passage(request)
        result = self.render_passage(passage, runtime_settings)
        if result.path is not None:
            print("\nImage Created.\n")

        if open_output and result.path is not None:
            self._image_opener(result.path)
        return result


# Private aliases retained for older callers and tests while public helpers are used
# by both front ends.
_output_path = default_output_path
_open_image = open_output


def build_generator(
    settings: Settings, *, content_client: Any | None = None
) -> QuranImageGenerator:
    """Construct the concrete command-line application without doing I/O."""

    from .content import QuranDataClient
    from .rendering import WandImageRenderer, WandTextMeasurer

    return QuranImageGenerator(
        settings=settings,
        content_client=(QuranDataClient() if content_client is None else content_client),
        measurer=WandTextMeasurer(),
        renderer=WandImageRenderer(),
    )
