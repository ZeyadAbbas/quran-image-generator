from wand.image import Image

from quran_image_generator.layout import (
    ImageLayout,
    PositionedLine,
    TextStyle,
    VerseMarker,
)
from quran_image_generator.overlays import render_overlay
from quran_image_generator.rendering import WandTextMeasurer
from quran_image_generator.resources import asset_path


def test_real_rgba_edges_and_crop_equivalence(tmp_path):
    style = TextStyle(asset_path("fonts","quran_font.ttf"),30,"#FFFFFF",0,240," ")
    text = "خَٰلِدِينَ فِيهَا"
    metrics = WandTextMeasurer().measure_ink(text,style)
    layout = ImageLayout(300,150,40,(PositionedLine(text,30,70,metrics,style),),())
    full = tmp_path / "full.png"
    crop = tmp_path / "crop.png"
    a,b = render_overlay(layout,full),render_overlay(layout,crop,cropped=True)
    assert a.bounds == b.bounds and a.alpha_mode == "straight"
    with Image(filename=str(full)) as image, Image(filename=str(crop)) as cropped:
        alpha = image.export_pixels(channel_map="A",storage="char")
        assert alpha[0] == 0 and max(alpha) == 255
        assert any(0 < v < 255 for v in alpha)
        with Image(width=300,height=150,background="transparent") as restored:
            restored.composite(cropped,*b.offset)
            assert restored.export_pixels(channel_map="RGBA",storage="char") == image.export_pixels(channel_map="RGBA",storage="char")


def test_blank_and_missing_required_marker(tmp_path):
    import pytest

    from quran_image_generator.references import ReferenceError
    blank = render_overlay(ImageLayout(30,20,0,(),()),tmp_path/"blank.png")
    assert blank.bounds is None
    with pytest.raises(ReferenceError, match="marker"):
        render_overlay(ImageLayout(30,20,0,(),(VerseMarker(7,1,1,5,5),)),tmp_path/"missing.png",marker_directory=tmp_path)
