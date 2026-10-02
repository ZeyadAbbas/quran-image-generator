"""Independent scene layers with RAQM shaping and reusable persistent assets."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .content import QuranDataClient
from .excerpts import Excerpt
from .overlays import OverlayAsset
from .references import ReferenceError
from .resources import asset_path
from .shaping import ShapedFont


@dataclass(frozen=True, slots=True)
class Layer:
    role: str
    text: str = ""
    font: str = ""
    image: str = ""
    font_size: int = 30
    anchor: tuple[float, float] = (0.5, 0.5)
    region: tuple[float, float, float, float] = (0.05, 0.05, 0.95, 0.95)
    direction: str = "rtl"
    color: str = "#FFFFFF"
    opacity: float = 1
    z_order: int = 0
    enabled: bool = True
    required: bool = True
    persistent: bool = False
    sha256: str = ""


@dataclass(frozen=True, slots=True)
class Scene:
    width: int
    height: int
    layers: tuple[Layer, ...]

    def validate(self) -> None:
        if any(type(v) is not int or not 16 <= v <= 4096 for v in (self.width,self.height)) or self.width*self.height > 8_500_000:
            raise ReferenceError("invalid_request", "Canvas must be 16..4096 pixels with at most 8.5 million pixels")
        if len(self.layers) > 16 or len({item.role for item in self.layers}) != len(self.layers):
            raise ReferenceError("invalid_request", "Layer roles must be unique, at most 16")
        for layer in self.layers:
            if not layer.role or not 0 <= layer.opacity <= 1 or layer.direction not in ("rtl","ltr"):
                raise ReferenceError("invalid_request", "Invalid layer role/opacity/direction")
            if not 1 <= layer.font_size <= 256 or len(layer.text) > 8000:
                raise ReferenceError("invalid_request", "Invalid font size or oversized layer text")
            if any(not math.isfinite(v) or not 0 <= v <= 1 for v in (*layer.anchor,*layer.region)) or layer.region[0] >= layer.region[2] or layer.region[1] >= layer.region[3]:
                raise ReferenceError("invalid_request", "Anchors and regions use normalized 0..1 coordinates")
            if layer.enabled and layer.required and not layer.text and not layer.image:
                raise ReferenceError("missing_asset", f"Required {layer.role} content is missing")


@dataclass(frozen=True, slots=True)
class LayerPlan:
    layer: Layer
    lines: tuple[tuple[str, float, float], ...]
    bounds: tuple[int,int,int,int] | None
    font_size: int
    asset_sha256: str
    status: str = "ready"


def checked_asset(path: str, expected_hash: str = "") -> str:
    selected = Path(path)
    if not path or not selected.is_file():
        raise ReferenceError("missing_asset", "Required local font/image asset is missing")
    if selected.stat().st_size > 32_000_000:
        raise ReferenceError("invalid_asset", "Asset exceeds 32 MB")
    digest = hashlib.sha256(selected.read_bytes()).hexdigest()
    if expected_hash and digest != expected_hash:
        raise ReferenceError("changed_asset", "Asset content hash changed")
    return digest


def layer_font(layer: Layer, size: int) -> ShapedFont:
    try:
        return ShapedFont(layer.font,size,layer.direction)
    except OSError as error:
        raise ReferenceError("missing_font", "Required font could not be loaded") from error


def plan_scene(scene: Scene) -> tuple[LayerPlan, ...]:
    scene.validate()
    plans = []
    for layer in sorted(scene.layers,key=lambda item:item.z_order):
        if not layer.enabled or not layer.text and not layer.image:
            plans.append(LayerPlan(layer,(),None,0,"","disabled" if not layer.enabled else "omitted_optional"))
            continue
        digest = checked_asset(layer.image or layer.font,layer.sha256)
        if layer.image:
            with Image.open(layer.image) as logo:
                max_w = (layer.region[2]-layer.region[0])*scene.width
                max_h = (layer.region[3]-layer.region[1])*scene.height
                scale = min(max_w/logo.width,max_h/logo.height)
                w,h = max(1,round(logo.width*scale)),max(1,round(logo.height*scale))
            image_x,image_y = round(layer.anchor[0]*scene.width-w/2),round(layer.anchor[1]*scene.height-h/2)
            plans.append(LayerPlan(layer,(),(image_x,image_y,image_x+w,image_y+h),0,digest))
            continue
        size = max(1,round(layer.font_size*scene.width/576))
        font = layer_font(layer,size)
        box = font.getbbox(layer.text,anchor="ls",direction=layer.direction)
        x = layer.anchor[0]*scene.width - (box[0]+box[2])/2
        y = layer.anchor[1]*scene.height
        bounds = (math.floor(x+box[0]),math.floor(y+box[1]),math.ceil(x+box[2]),math.ceil(y+box[3]))
        allowed = tuple(round(v*(scene.width if i%2 == 0 else scene.height)) for i,v in enumerate(layer.region))
        if bounds[0]<allowed[0] or bounds[1]<allowed[1] or bounds[2]>allowed[2] or bounds[3]>allowed[3]:
            raise ReferenceError("layout_overflow", f"{layer.role} exceeds its region; split the phrase or enlarge the region")
        plans.append(LayerPlan(layer,((layer.text,x,y),),bounds,size,digest))
    return tuple(plans)


def render_layer(scene: Scene, plan: LayerPlan, destination: Path, *, cropped: bool = False) -> OverlayAsset:
    with Image.new("RGBA",(scene.width,scene.height),(0,0,0,0)) as image:
        layer = plan.layer
        if plan.status == "ready":
            checked_asset(layer.image or layer.font,plan.asset_sha256)
            if layer.image and plan.bounds:
                left,top,right,bottom = plan.bounds
                with Image.open(layer.image) as original:
                    with original.convert("RGBA") as rgba:
                        with rgba.resize((right-left,bottom-top),Image.Resampling.LANCZOS) as logo:
                            image.alpha_composite(logo,(left,top))
            else:
                font = layer_font(layer,plan.font_size)
                for text,x,y in plan.lines:
                    font.paint(image,text,x,y,layer.color)
            if layer.opacity != 1:
                with image.getchannel("A") as alpha:
                    image.putalpha(alpha.point(lambda a:round(a*layer.opacity)))
        with image.getchannel("A") as alpha:
            bounds = alpha.getbbox()
        offset = (0,0)
        if cropped and bounds:
            offset = (bounds[0],bounds[1])
            with image.crop(bounds) as crop:
                crop.save(destination,"PNG")
                width,height = crop.size
        else:
            image.save(destination,"PNG")
            width,height = image.size
        return OverlayAsset(hashlib.sha256(destination.read_bytes()).hexdigest(),width,height,offset,bounds)


def caption_scene(excerpt: Excerpt, *, width: int = 576, height: int = 1024,
                  english: str = "", titles: bool = False, logo: str = "",
                  arabic_title: str = "", latin_title: str = "") -> Scene:
    arabic_font = str(asset_path("fonts","quran_font.ttf"))
    latin_font = str(asset_path("fonts","multilingual_fonts","am.ttf"))
    layers = [Layer("arabic",excerpt.text,arabic_font,font_size=30,anchor=(.5,.5),region=(.05,.35,.95,.53))]
    if english:
        layers.append(Layer("translation",english,latin_font,font_size=16,anchor=(.5,.56),region=(.05,.53,.95,.68),direction="ltr",z_order=1))
    if titles:
        surah = next((s.source.surah for s in excerpt.spans if s.source.surah),None)
        if surah is None:
            # Caller must supply an actual upcoming chapter for an opening basmala.
            raise ReferenceError("invalid_reference", "Separate basmala needs an explicit title override or titles disabled")
        chapter = QuranDataClient().get_chapter(surah)
        layers.extend((Layer("arabic_title",arabic_title or f"سورة {chapter.name_arabic}",arabic_font,font_size=25,anchor=(.5,.16),region=(.05,.08,.95,.18),persistent=True),
                       Layer("latin_title",latin_title or f"Surah {chapter.name_simple}",latin_font,font_size=15,anchor=(.5,.20),region=(.05,.18,.95,.25),direction="ltr",persistent=True)))
    if logo:
        layers.append(Layer("logo",image=logo,anchor=(.5,.9),region=(.35,.84,.65,.96),persistent=True,z_order=5))
    return Scene(width,height,tuple(layers))
