"""Lazy still-image adapters: Pillow by default, optional native ImageMagick."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .layout import ImageLayout, TextMetrics, TextStyle
from .pillow_text import shaped_font, text_direction
from .references import ReferenceError
from .render_cache import RenderCache, file_identity
from .resources import asset_path
from .settings import Settings


class PillowTextMeasurer:
    def __init__(self) -> None:
        self._metrics: RenderCache[tuple, TextMetrics] = RenderCache(
            8192, max_bytes=16 * 1024 * 1024
        )

    def measure(self, text: str, style: TextStyle) -> TextMetrics:
        from .pillow_text import font_path

        direction = (
            text_direction(text)
            if style.direction == "undefined"
            else ("rtl" if style.direction == "right_to_left" else "ltr")
        )
        path = font_path(style.font, direction=direction)
        key = (
            text,
            file_identity(path),
            style.font_size,
            style.letter_spacing,
            style.additional_word_spacing,
            direction,
            style.font_sha256,
        )
        cached = self._metrics.get(key)
        if cached is not None:
            return cached
        font = shaped_font(
            path,
            style.font_size,
            direction=direction,
            letter_spacing=style.letter_spacing,
            word_spacing=style.additional_word_spacing,
            sha256=style.font_sha256,
        )
        left, top, right, bottom = font.getbbox(text, anchor="ls", direction=direction)
        ascender, descender = font.getmetrics()
        result = TextMetrics(
            float(font.getlength(text, direction=direction)),
            bottom - top,
            ascender,
            descender,
            max(0, -top),
            max(0, bottom),
            left,
            right,
        )
        self._metrics.put(key, result, size=len(text) * 4 + 256)
        return result

    measure_ink = measure


class PillowImageRenderer:
    def __init__(self) -> None:
        self._images: RenderCache[tuple, Image.Image] = RenderCache(
            128, dispose=lambda image: image.close()
        )

    def _image(self, path: Path, size: tuple[int, int] | None = None) -> Image.Image:
        key = file_identity(path), size
        cached = self._images.copy(key, lambda image: image.copy())
        if cached is not None:
            return cached
        try:
            with Image.open(path) as source:
                image: Image.Image = source.convert("RGBA")
        except OSError:
            # SVG and other optional formats keep native decoding when installed.
            from wand.image import Image as WandImage

            from .rendering import wand_rgba_image

            with WandImage(filename=str(path)) as source:
                image = wand_rgba_image(source)
        if size:
            original = image
            image = image.resize(size, Image.Resampling.LANCZOS)
            original.close()
        cost = image.width * image.height * 4
        if cost <= self._images.max_bytes:
            owned = image.copy()
            self._images.put(key, image, size=cost)
            return owned
        return image

    def render(
        self, layout: ImageLayout, settings: Settings, destination: Path
    ) -> Path:
        with Image.new(
            "RGBA", (layout.width, layout.height), settings.background_color
        ) as image:
            if settings.background_image is not None:
                with self._image(settings.background_image) as background:
                    image.alpha_composite(background, (0, 0))
            for marker in layout.markers:
                path = asset_path("verse_numbers", f"{marker.number}.png")
                try:
                    with self._image(
                        path, (marker.width, marker.height)
                    ) as marker_image:
                        image.alpha_composite(
                            marker_image, (int(marker.x), int(marker.y))
                        )
                except Exception as error:  # legacy markers remain non-fatal
                    print(f"Error loading {path}: {error}")
            with Image.new("RGBA", image.size) as glyphs:
                draw = ImageDraw.Draw(glyphs)
                for line in layout.lines:
                    style = line.style
                    direction = (
                        text_direction(line.text)
                        if style.direction == "undefined"
                        else ("rtl" if style.direction == "right_to_left" else "ltr")
                    )
                    font = shaped_font(
                        style.font,
                        style.font_size,
                        direction=direction,
                        letter_spacing=style.letter_spacing,
                        word_spacing=style.additional_word_spacing,
                        sha256=style.font_sha256,
                    )
                    draw.text(
                        (int(line.x), int(line.y)),
                        line.text,
                        font=font,
                        fill=style.color,
                        anchor="ls",
                        direction=direction,
                    )
                image.alpha_composite(glyphs)
            image.save(destination, "PNG")
        return destination

    def close(self) -> None:
        self._images.clear()


class BackendMeasurer:
    def __init__(self) -> None:
        self._adapters: dict[str, Any] = {}

    def for_backend(self, backend: str) -> Any:
        if backend not in self._adapters:
            if backend == "pillow":
                adapter: Any = PillowTextMeasurer()
            elif backend == "imagemagick":
                try:
                    from .rendering import WandTextMeasurer

                    adapter = WandTextMeasurer()
                except (ImportError, OSError) as error:
                    raise ReferenceError(
                        "missing_native_runtime",
                        "ImageMagick rendering requires Wand and the native ImageMagick "
                        "libraries. Install them or select the pillow render backend.",
                        details={"field": "render_backend"},
                    ) from error
            else:
                raise ValueError("Render backend must be pillow or imagemagick")
            self._adapters[backend] = adapter
        return self._adapters[backend]


class BackendRenderer:
    def __init__(self) -> None:
        self._adapters: dict[str, Any] = {}

    def render(
        self, layout: ImageLayout, settings: Settings, destination: Path
    ) -> Path:
        backend = settings.render_backend
        if backend not in self._adapters:
            if backend == "pillow":
                adapter: Any = PillowImageRenderer()
            elif backend == "imagemagick":
                try:
                    from .rendering import WandImageRenderer

                    adapter = WandImageRenderer()
                except (ImportError, OSError) as error:
                    raise ReferenceError(
                        "missing_native_runtime",
                        "ImageMagick rendering requires Wand and the native ImageMagick "
                        "libraries. Install them or select the pillow render backend.",
                        details={"field": "render_backend"},
                    ) from error
            else:
                raise ValueError("Render backend must be pillow or imagemagick")
            self._adapters[backend] = adapter
        return Path(self._adapters[backend].render(layout, settings, destination))

    def close(self) -> None:
        for adapter in self._adapters.values():
            adapter.close()
