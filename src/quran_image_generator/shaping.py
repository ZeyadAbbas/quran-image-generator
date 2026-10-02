"""RAQM text adapter: Pillow where available, native Wand otherwise."""

from __future__ import annotations

import re
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, features

from .layout import TextStyle
from .references import ReferenceError


class ShapedFont:
    def __init__(
        self, path: str, size: int | float, direction: str, horizontal_scale: float = 1
    ) -> None:
        if size > 512:
            raise ReferenceError(
                "resource_limit", "Effective font size exceeds 512 pixels"
            )
        self.path, self.size, self.direction = path, size, direction
        self.horizontal_scale = horizontal_scale
        self.pillow: ImageFont.FreeTypeFont | None = None
        if features.check_feature("raqm"):
            self.pillow = ImageFont.truetype(
                path, size, layout_engine=ImageFont.Layout.RAQM
            )
        else:
            from wand.version import MAGICK_VERSION_DELEGATES

            if "raqm" not in MAGICK_VERSION_DELEGATES.split():
                raise ReferenceError(
                    "missing_shaping",
                    "Install Pillow or ImageMagick with RAQM/Harfbuzz support",
                )

    def space_width(self) -> float:
        if self.pillow:
            return (
                float(self.pillow.getlength(" ", direction=self.direction))
                * self.horizontal_scale
            )
        from .rendering import WandTextMeasurer

        return (
            float(
                WandTextMeasurer()
                .measure(
                    " ",
                    TextStyle(
                        self.path,
                        self.size,
                        "#FFFFFF",
                        0,
                        8192,
                        " ",
                        "right_to_left" if self.direction == "rtl" else "left_to_right",
                    ),
                )
                .width
            )
            * self.horizontal_scale
        )

    def getbbox(self, text: str, **kwargs: object) -> tuple[float, float, float, float]:
        left, top, right, bottom = self._bbox(text)
        return left * self.horizontal_scale, top, right * self.horizontal_scale, bottom

    def _bbox(self, text: str) -> tuple[float, float, float, float]:
        if self.pillow:
            return self.pillow.getbbox(text, anchor="ls", direction=self.direction)
        from .rendering import WandTextMeasurer

        style = TextStyle(
            self.path,
            self.size,
            "#FFFFFF",
            0,
            8192,
            " ",
            "right_to_left" if self.direction == "rtl" else "left_to_right",
        )
        measurer = WandTextMeasurer()
        if measurer.measure(text, style).width > 16384:
            raise ReferenceError(
                "layout_overflow",
                "Unbroken shaped line exceeds 16384 pixels; split the cue",
            )
        metrics = measurer.measure_ink(text, style)
        return (
            metrics.left_offset,
            -metrics.visual_top_extent,
            metrics.visual_right_offset,
            metrics.visual_bottom_extent,
        )

    def paint(
        self, image: Image.Image, text: str, x: float, y: float, color: str
    ) -> None:
        if self.horizontal_scale != 1:
            left, top, right, bottom = self._bbox(text)
            with Image.new(
                "RGBA",
                (max(1, round(right - left) + 4), max(1, round(bottom - top) + 4)),
            ) as tile:
                bx, by = round(2 - left), round(2 - top)
                self._paint(tile, text, bx, by, color)
                ink = tile.getbbox()
                if ink:
                    with (
                        tile.crop(ink) as crop,
                        crop.resize(
                            (
                                max(1, round(crop.width * self.horizontal_scale)),
                                crop.height,
                            ),
                            Image.Resampling.LANCZOS,
                        ) as scaled,
                    ):
                        image.alpha_composite(
                            scaled,
                            (
                                round(x + (ink[0] - bx) * self.horizontal_scale),
                                round(y + ink[1] - by),
                            ),
                        )
            return
        self._paint(image, text, x, y, color)

    def _paint(
        self, image: Image.Image, text: str, x: float, y: float, color: str
    ) -> None:
        if self.pillow:
            ImageDraw.Draw(image).text(
                (x, y),
                text,
                font=self.pillow,
                fill=color,
                anchor="ls",
                direction=self.direction,
            )
            return
        from wand.drawing import Drawing
        from wand.image import Image as WandImage

        with (
            WandImage(
                width=image.width, height=image.height, background="transparent"
            ) as raster,
            Drawing() as draw,
        ):
            draw.font = self.path
            draw.font_size = self.size
            draw.fill_color = color
            draw.text_direction = (
                "right_to_left" if self.direction == "rtl" else "left_to_right"
            )
            draw.text(round(x), round(y), text)
            draw(raster)
            with Image.open(BytesIO(raster.make_blob("png"))) as rendered:
                with rendered.convert("RGBA") as rgba:
                    image.alpha_composite(rgba)


class MixedMarkerFont:
    """Keep Arabic runs shaped intact, with separate small verse-number glyphs."""

    def __init__(
        self,
        primary: ShapedFont,
        marker: ShapedFont,
        markers: tuple[str, ...],
        offset: float = 0,
    ) -> None:
        self.primary, self.marker = primary, marker
        self.offset = offset
        self.pattern = re.compile(
            "("
            + "|".join(
                re.escape(v) for v in sorted(set(markers), key=len, reverse=True)
            )
            + ")"
        )
        self.markers = set(markers)
        self.space_width = primary.space_width()

    def _runs(
        self, text: str
    ) -> list[tuple[str, ShapedFont, tuple[float, float, float, float], float]]:
        runs = []
        for part in self.pattern.split(text):
            visible = part.strip()
            if not visible:
                continue
            font = self.marker if visible in self.markers else self.primary
            box = font.getbbox(visible)
            if font is self.marker:
                box = (box[0], box[1] + self.offset, box[2], box[3] + self.offset)
            # The split is only at ayah markers, never inside Arabic words.
            gap = max(0, len(part) - len(visible)) * self.space_width
            runs.append((visible, font, box, gap))
        return runs

    def getbbox(self, text: str, **kwargs: object) -> tuple[float, float, float, float]:
        runs = self._runs(text)
        if not runs:
            return (0, 0, 0, 0)
        return (
            0,
            min(r[2][1] for r in runs),
            sum(r[2][2] - r[2][0] + r[3] for r in runs),
            max(r[2][3] for r in runs),
        )

    def paint(
        self, image: Image.Image, text: str, x: float, y: float, color: str
    ) -> None:
        runs = self._runs(text)
        rtl = self.primary.direction == "rtl"
        cursor = x + self.getbbox(text)[2] if rtl else x
        for value, font, box, gap in runs:
            if rtl:
                cursor -= box[2] - box[0] + gap
            font.paint(
                image,
                value,
                cursor - box[0] + gap / 2,
                y + (self.offset if font is self.marker else 0),
                color,
            )
            if not rtl:
                cursor += box[2] - box[0] + gap
