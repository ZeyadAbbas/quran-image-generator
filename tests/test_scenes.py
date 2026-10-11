from PIL import Image

from quran_image_generator.excerpts import ExcerptRequest, select_excerpt
from quran_image_generator.references import SourceSpan
from quran_image_generator.scenes import caption_scene, plan_scene, render_layer


def test_independent_persistent_layers_and_logo_contain(tmp_path):
    logo = tmp_path / "original logo.png"
    with Image.new("RGBA",(100,50),(255,255,255,128)) as image:
        image.save(logo)
    excerpt = select_excerpt(ExcerptRequest("a",(SourceSpan(31,9,1,5),)))
    scene = caption_scene(excerpt,titles=True,logo=str(logo))
    plans = plan_scene(scene)
    assert [p.layer.role for p in plans] == ["arabic","arabic_title","latin_title","logo"]
    branding = plans[-1]
    assert branding.layer.persistent
    left,top,right,bottom = branding.bounds
    assert abs((right-left)/(bottom-top)-2) < .03
    for plan in plans:
        asset = render_layer(scene,plan,tmp_path/f"{plan.layer.role}.png")
        assert asset.bounds and asset.alpha_mode == "straight"
    short = caption_scene(select_excerpt(ExcerptRequest("b",(SourceSpan(31,11,1,3),))),titles=True,logo=str(logo))
    assert [p.bounds for p in plan_scene(short)[1:]] == [p.bounds for p in plans[1:]]
