"""RAQM text adapter: Pillow where available, native Wand otherwise."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, features

from .layout import TextStyle
from .references import ReferenceError


class ShapedFont:
    def __init__(self, path: str, size: int, direction: str) -> None:
        self.path, self.size, self.direction = path, size, direction
        self.pillow: ImageFont.FreeTypeFont | None = None
        if features.check_feature("raqm"):
            self.pillow = ImageFont.truetype(path,size,layout_engine=ImageFont.Layout.RAQM)
        else:
            from wand.version import MAGICK_VERSION_DELEGATES
            if "raqm" not in MAGICK_VERSION_DELEGATES.split():
                raise ReferenceError("missing_shaping", "Install Pillow or ImageMagick with RAQM/Harfbuzz support")

    def getbbox(self, text: str, **kwargs: object) -> tuple[float,float,float,float]:
        if self.pillow:
            return self.pillow.getbbox(text,anchor="ls",direction=self.direction)
        from .rendering import WandTextMeasurer
        style = TextStyle(self.path,self.size,"#FFFFFF",0,8192," ","right_to_left" if self.direction == "rtl" else "left_to_right")
        metrics = WandTextMeasurer().measure_ink(text,style)
        return metrics.left_offset,-metrics.visual_top_extent,metrics.visual_right_offset,metrics.visual_bottom_extent

    def paint(self, image: Image.Image, text: str, x: float, y: float, color: str) -> None:
        if self.pillow:
            ImageDraw.Draw(image).text((x,y),text,font=self.pillow,fill=color,anchor="ls",direction=self.direction)
            return
        from wand.drawing import Drawing
        from wand.image import Image as WandImage
        with WandImage(width=image.width,height=image.height,background="transparent") as raster, Drawing() as draw:
            draw.font = self.path
            draw.font_size = self.size
            draw.fill_color = color
            draw.text_direction = "right_to_left" if self.direction == "rtl" else "left_to_right"
            draw.text(round(x),round(y),text)
            draw(raster)
            with Image.open(BytesIO(raster.make_blob("png"))) as rendered:
                image.alpha_composite(rendered.convert("RGBA"))
