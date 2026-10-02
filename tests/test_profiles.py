from dataclasses import replace

import pytest
from PIL import Image

from quran_image_generator.excerpts import ExcerptRequest, select_excerpt
from quran_image_generator.profiles import (
    creator_profile,
    decorate_excerpt,
    export_profile,
    import_profile,
)
from quran_image_generator.references import ReferenceError, SourceSpan
from quran_image_generator.scenes import caption_scene, plan_scene, render_layer


def test_effects_and_profile_roundtrip_preserve_source(tmp_path):
    excerpt = select_excerpt(ExcerptRequest("a", (SourceSpan(39, 30, 4, 4),)))
    scene = decorate_excerpt(excerpt, caption_scene(excerpt))
    profile = creator_profile(scene)
    assert profile.approval == "needs_review"
    path = tmp_path / "profile.json"
    export_profile(profile, path)
    assert import_profile(path) == profile
    scene = profile.apply(scene)
    assert excerpt.text not in ("﴿", "﴾") and "﴿" not in excerpt.text
    plan = plan_scene(scene)[0]
    assert plan.suffix_position is not None
    asset = render_layer(scene, plan, tmp_path / "effect.png")
    assert all(a >= b for a, b in zip(asset.bounds[:2], plan.bounds[:2], strict=True))
    assert all(a <= b for a, b in zip(asset.bounds[2:], plan.bounds[2:], strict=True))
    with Image.open(tmp_path / "effect.png") as image:
        assert image.getpixel((0, 0))[3] == 0


def test_missing_glyph_is_a_failure():
    excerpt = select_excerpt(ExcerptRequest("a", (SourceSpan(31, 9, 1, 5),)))
    scene = caption_scene(excerpt)
    scene = replace(scene, layers=(replace(scene.layers[0], text="🚀"),))
    with pytest.raises(ReferenceError) as error:
        plan_scene(scene)
    assert error.value.code == "missing_glyph"
