from dataclasses import replace

import pytest

from quran_image_generator.caption_fit import FitError
from quran_image_generator.excerpts import ExcerptRequest, select_excerpt
from quran_image_generator.references import SourceSpan
from quran_image_generator.scenes import caption_scene, plan_scene


def test_wrapping_keeps_baseline_and_independent_english():
    excerpt = select_excerpt(ExcerptRequest("a", (SourceSpan(31, 9, 1, 5),)))
    scene = caption_scene(
        excerpt,
        english="Authored English caption with enough words to wrap independently into several readable lines for testing.",
    )
    first = plan_scene(scene)
    longer = replace(
        scene,
        layers=(
            replace(
                scene.layers[0], text=scene.layers[0].text + " " + scene.layers[0].text
            ),
            scene.layers[1],
        ),
    )
    second = plan_scene(longer)
    assert second[0].lines[-1][2] == first[0].lines[-1][2] == 0.5 * 1024
    assert first[1] == second[1]
    assert len(first[1].lines) > 1


def test_too_small_region_reports_details_without_truncation():
    excerpt = select_excerpt(ExcerptRequest("a", (SourceSpan(31, 9, 1, 5),)))
    scene = caption_scene(excerpt)
    layer = replace(
        scene.layers[0], region=(0.49, 0.49, 0.51, 0.51), fit="shrink", min_font_size=24
    )
    with pytest.raises(FitError) as error:
        plan_scene(replace(scene, layers=(layer,)))
    assert error.value.details["suggestions"][0] == "split_cue"
    assert error.value.details["font_size"] == 24
    assert layer.text == excerpt.text


@pytest.mark.parametrize(
    "width,height", [(576, 1024), (1080, 1920), (480, 800), (1280, 720)]
)
def test_scaled_dimensions_and_rtl_are_deterministic(width, height):
    excerpt = select_excerpt(ExcerptRequest("a", (SourceSpan(31, 11, 1, 3),)))
    scene = caption_scene(excerpt, width=width, height=height)
    # Landscape gets an explicitly larger caption region rather than guessing a new profile.
    if width > height:
        scene = replace(
            scene, layers=(replace(scene.layers[0], region=(0.05, 0.2, 0.95, 0.7)),)
        )
    assert plan_scene(scene) == plan_scene(scene)
