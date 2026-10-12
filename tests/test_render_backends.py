"""Backend selection, exact native compatibility and cached-input regressions."""

import hashlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from math import ceil

import pytest
from fontTools.ttLib import TTCollection, TTFont
from PIL import Image
from test_api import fixture_request
from test_group_layout import group_request
from wand.drawing import Drawing
from wand.image import Image as WandImage

from quran_image_generator import rendering
from quran_image_generator.api import (
    RenderRequest,
    capabilities,
    execute_request,
    runtime_identity,
)
from quran_image_generator.backends import using_backend
from quran_image_generator.content import QuranDataClient
from quran_image_generator.generator import build_generator
from quran_image_generator.layout import TextStyle, build_layout
from quran_image_generator.models import GenerationRequest
from quran_image_generator.pillow_text import shaped_font
from quran_image_generator.references import ReferenceError
from quran_image_generator.render_cache import CaptionRenderCache, RenderCache
from quran_image_generator.rendering import WandImageRenderer, WandTextMeasurer
from quran_image_generator.resources import asset_path
from quran_image_generator.settings import (
    SettingsValidationError,
    settings_from_mapping,
    settings_to_mapping,
)
from quran_image_generator.shaping import ShapedFont


def test_backend_defaults_round_trip_and_reject_invalid_values(tmp_path):
    settings = settings_from_mapping({}, source_path=tmp_path / "config.yaml")
    assert settings.render_backend == "pillow"
    mapping = settings_to_mapping(replace(settings, render_backend="imagemagick"))
    assert (
        settings_from_mapping(mapping, source_path=settings.source_path).render_backend
        == "imagemagick"
    )
    assert (
        RenderRequest.from_dict(fixture_request(tmp_path)).payload["render_backend"]
        == "pillow"
    )
    for invalid in ("auto", "fast", True, 1):
        with pytest.raises(SettingsValidationError):
            settings_from_mapping({"render backend": invalid})
        response = execute_request(
            {**fixture_request(tmp_path), "render_backend": invalid}
        ).to_dict()
        assert response["status"] == "failed"
        assert response["error"]["details"]["path"] == "/render_backend"


def test_one_generator_switches_measurement_and_painting_backends(tmp_path):
    settings = settings_from_mapping(
        {"quran font": str(asset_path("fonts", "quran_font.ttf"))},
        source_path=tmp_path / "config.yaml",
    )
    generator = build_generator(settings)
    _, passage = generator.fetch_passage(GenerationRequest(1, 1, 1))
    for backend in ("pillow", "imagemagick", "pillow"):
        result = generator.render_passage(
            passage,
            replace(settings, render_backend=backend),
            destination=tmp_path / f"{backend}.png",
        )
        assert result.path and result.path.is_file()
        with Image.open(result.path) as image:
            assert image.size == (1080, 1080)
    assert set(generator._measurer._adapters) == {"pillow", "imagemagick"}
    assert set(generator._renderer._adapters) == {"pillow", "imagemagick"}
    generator.close()


@pytest.mark.parametrize("backend", ["pillow", "imagemagick"])
def test_caption_backend_is_explicit_and_cache_cannot_cross_backends(tmp_path, backend):
    cache = CaptionRenderCache()
    data = {**fixture_request(tmp_path), "render_backend": backend}
    first = execute_request(data, cache=cache).to_dict()
    if backend == "imagemagick" and not runtime_identity()["native_raqm"]:
        assert first["status"] == "failed"
        assert first["cues"][0]["error"]["code"] == "missing_shaping"
        return
    assert first["status"] == "complete"
    expected = "pillow_raqm" if backend == "pillow" else "wand_raqm"
    assert first["cues"][0]["layers"][0]["typography"]["backend"] == expected
    changed = execute_request(
        {**data, "render_backend": "imagemagick" if backend == "pillow" else "pillow"},
        cache=cache,
    ).to_dict()
    if backend == "pillow" and not runtime_identity()["native_raqm"]:
        assert changed["status"] == "failed"
        assert changed["cues"][0]["error"]["code"] == "missing_shaping"
        return
    assert changed["status"] == "complete"
    assert first["assets"][0]["asset_id"] != changed["assets"][0]["asset_id"]
    assert first["cues"][0]["arabic"] == changed["cues"][0]["arabic"]


def test_pillow_caps_and_still_images_work_without_any_magick_import(tmp_path):
    # Run in a fresh process; importing Wand is forbidden, rather than merely
    # hidden after it was already initialized by the test runner.
    code = """
import builtins
import json
from dataclasses import replace
from pathlib import Path
original = builtins.__import__
def isolated(name, *args, **kwargs):
    if name == 'wand' or name.startswith('wand.'):
        raise ImportError('ImageMagick deliberately unavailable')
    return original(name, *args, **kwargs)
builtins.__import__ = isolated
from quran_image_generator.api import execute_request
from quran_image_generator.caption_editor import CaptionDocument
from quran_image_generator.content import QuranDataClient
from quran_image_generator.generator import build_generator
from quran_image_generator.models import GenerationRequest
from quran_image_generator.resources import asset_path
from quran_image_generator.settings import settings_from_mapping
from PIL import Image
root = Path.cwd()
background = root / 'background.png'
Image.new('RGB', (1080,1080), '#102030').save(background)
settings = settings_from_mapping({'quran font': str(asset_path('fonts','quran_font.ttf')),
    'background image':str(background),'resolution':'bg'}, source_path=root/'config.yaml')
generator = build_generator(settings)
_, passage = generator.fetch_passage(GenerationRequest(1,1,1))
generator.render_passage(passage,settings,destination=root/'still.png')
payload = CaptionDocument(root=root).request().to_dict()
payload.update(output_directory=str(root/'captions'),titles=True,quotations=True,verse_numbers=True)
response = execute_request(payload).to_dict()
assert response['status']=='complete',response
assert response['runtime']['imagemagick']=='unavailable'
assert response['cues'][0]['layers'][0]['typography']['backend']=='pillow_raqm'
payload['operation']='preflight'
assert execute_request(payload).to_dict()['preflight']['ready']
payload.update(operation='render_batch',render_backend='imagemagick')
missing = execute_request(payload).to_dict()
assert missing['status']=='failed',missing
assert missing['cues'][0]['error']['code']=='missing_native_runtime',missing
generator.close()
print('pillow-only passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "pillow-only passed" in result.stdout


def test_missing_pillow_shaping_is_actionable_and_never_falls_back(
    monkeypatch, tmp_path
):
    from quran_image_generator import backends

    monkeypatch.setattr(
        __import__("PIL.features", fromlist=["features"]),
        "check_feature",
        lambda _: False,
    )
    with using_backend("pillow"), pytest.raises(ReferenceError) as error:
        ShapedFont(str(asset_path("fonts", "quran_font.ttf")), 30, "rtl")
    assert error.value.code == "missing_shaping"
    assert "imagemagick" in str(error.value)
    response = execute_request(fixture_request(tmp_path)).to_dict()
    assert response["status"] == "failed"
    assert response["cues"][0]["error"]["code"] == "missing_shaping"
    assert backends.selected_backend() == "auto"


def _legacy_ink(text, style):
    # Independent oracle: retain the previous native draw/trim measurement.
    with WandImage(width=1, height=1) as image, Drawing() as draw:
        rendering._apply_style(draw, style)
        measured = draw.get_font_metrics(image, text)
    padding = (
        ceil(
            max(
                measured.text_height,
                measured.ascender,
                -measured.descender,
                style.font_size,
                1,
            )
        )
        + 2
    )
    for _ in range(4):
        baseline = padding * 2
        width = max(1, ceil(measured.text_width) + padding * 2 + 1)
        height = padding * 4 + 1
        with (
            WandImage(width=width, height=height, pseudo="xc:#000000") as image,
            Drawing() as draw,
        ):
            rendering._apply_style(draw, style)
            draw.fill_color = "#FFFFFF"
            draw.text(padding, baseline, text)
            draw(image)
            image.trim()
            bounds = (
                image.page_x,
                image.page_y,
                image.page_x + image.width,
                image.page_y + image.height,
            )
        left, top, right, bottom = bounds
        if left > 0 and top > 0 and right < width and bottom < height:
            return left - padding, baseline - top, right - padding, bottom - baseline
        padding *= 2
    pytest.fail("Reference ink measurement could not fit its raster")


@pytest.mark.parametrize(
    "text", ["بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ", "ٱللَّهُ ﴿٢٥٥﴾", "سورة البقرة"]
)
@pytest.mark.parametrize("size", [12, 38, 75])
def test_float_native_bounds_equal_original_trim_bounds(text, size):
    style = TextStyle(
        asset_path("fonts", "quran_font.ttf"),
        size,
        "#ABCDEF",
        -0.1,
        900,
        " ",
        "right_to_left",
    )
    metrics = WandTextMeasurer().measure_ink(text, style)
    assert (
        metrics.left_offset,
        metrics.visual_top_extent,
        metrics.visual_right_offset,
        metrics.visual_bottom_extent,
    ) == _legacy_ink(text, style)


def test_color_and_wrap_width_reuse_native_geometry(monkeypatch):
    style = TextStyle(asset_path("fonts", "quran_font.ttf"), 37, "#FFFFFF", 0, 900, " ")
    measurer = WandTextMeasurer()
    original = measurer.measure_ink("خَٰلِدِينَ فِيهَا", style)
    monkeypatch.setattr(
        rendering,
        "_apply_style",
        lambda *args: pytest.fail("Color/width edit repeated native work"),
    )
    assert (
        measurer.measure_ink(
            "خَٰلِدِينَ فِيهَا", replace(style, color="#EEEEEE", max_width=800)
        )
        is original
    )


def test_native_cached_images_retain_full_precision_and_reload_changes(
    tmp_path, monkeypatch
):
    background = tmp_path / "background.png"
    Image.new("RGBA", (640, 420), "#124466").save(background)
    settings = settings_from_mapping(
        {
            "render backend": "imagemagick",
            "resolution": "640 x 420",
            "background image": str(background),
            "quran font": str(asset_path("fonts", "quran_font.ttf")),
            "quran font size": 30,
            "quran maximum width": 560,
            "show verse numbers": True,
        },
        source_path=tmp_path / "config.yaml",
    )
    passage = QuranDataClient().fetch_passage(GenerationRequest(1, 1, 1), ())
    layout = build_layout(passage, settings, WandTextMeasurer())
    renderer = WandImageRenderer()
    native_image = rendering.Image
    reads = []

    def counted(**kwargs):
        if "filename" in kwargs:
            reads.append(kwargs["filename"])
        return native_image(**kwargs)

    monkeypatch.setattr(rendering, "Image", counted)
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    renderer.render(layout, settings, first)
    count = len(reads)
    renderer.render(layout, settings, second)
    assert len(reads) == count
    with WandImage(filename=str(first)) as a, WandImage(filename=str(second)) as b:
        assert a.signature == b.signature
        assert a.depth == b.depth
    Image.new("RGBA", (640, 420), "#664412").save(background)
    third = tmp_path / "third.png"
    renderer.render(layout, settings, third)
    assert len(reads) == count + 1
    with WandImage(filename=str(first)) as a, WandImage(filename=str(third)) as c:
        assert a.signature != c.signature
    renderer.close()


@pytest.mark.parametrize("backend", ["pillow", "imagemagick"])
def test_cached_plans_and_pngs_reused_but_inputs_and_output_still_verified(
    tmp_path, monkeypatch, backend
):
    from quran_image_generator import api

    if backend == "imagemagick" and not runtime_identity()["native_raqm"]:
        pytest.skip("Native caption shaping needs an ImageMagick RAQM build")

    cache = CaptionRenderCache()
    data = {**fixture_request(tmp_path), "render_backend": backend}
    first = execute_request(data, cache=cache).to_dict()
    assert first["status"] == "complete"
    monkeypatch.setattr(
        api, "plan_scene", lambda _: pytest.fail("Unchanged scene was fitted again")
    )
    monkeypatch.setattr(
        api,
        "render_layer",
        lambda *a, **k: pytest.fail("Unchanged layer was painted again"),
    )
    second = execute_request(data, cache=cache).to_dict()
    assert second["status"] == "complete"
    assert first["job_directory"] != second["job_directory"]
    assert first["assets"] == second["assets"]
    bad = dict(data)
    bad["source_corpus"] = {**data["source_corpus"], "sha256": "0" * 64}
    assert (
        execute_request(bad, cache=cache).to_dict()["error"]["code"]
        == "unsupported_corpus"
    )
    key = second["assets"][0]["asset_id"]
    raw, record = cache.assets.get(key)
    cache.assets.put(key, (b"corrupt", record))
    broken = execute_request(data, cache=cache).to_dict()
    assert broken["status"] == "failed" and broken["error"]["code"] == "output_io"


def test_cached_collection_faces_bind_to_new_job_paths(tmp_path, monkeypatch):
    from quran_image_generator import api

    collection = TTCollection()
    collection.fonts = [TTFont(asset_path("fonts", "quran_font.ttf")) for _ in range(2)]
    source = tmp_path / "faces.ttc"
    collection.save(source)
    collection.close()
    data = fixture_request(tmp_path)
    data["assets"] = {
        "arabic": {
            "path": str(source),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "license": "test",
            "attribution": "test",
        }
    }
    data["profile"] = {
        "id": "plain",
        "revision": "1",
        "approval": "approved",
        "provenance": {},
        "styles": {"arabic": {"font_face": 1}},
    }
    cache = CaptionRenderCache()
    first = execute_request(data, cache=cache).to_dict()
    assert first["status"] == "complete", first
    monkeypatch.setattr(
        api, "plan_scene", lambda _: pytest.fail("Collection scene fitted again")
    )
    # Force painting so an expired job-local font path cannot hide behind PNG reuse.
    cache.assets.clear()
    second = execute_request(data, cache=cache).to_dict()
    assert second["status"] == "complete", second
    assert first["assets"] == second["assets"]


@pytest.mark.parametrize("backend", ["pillow", "imagemagick"])
def test_cached_group_panels_and_decorations_repaint_at_identical_positions(
    tmp_path, monkeypatch, backend
):
    from quran_image_generator import api

    if backend == "imagemagick" and not runtime_identity()["native_raqm"]:
        pytest.skip("Native caption shaping needs an ImageMagick RAQM build")

    data = group_request(tmp_path)
    data.update(render_backend=backend, quotations=True, verse_numbers=True)
    data["profile"] = {
        "id": "plain", "revision": "1", "approval": "approved", "provenance": {},
        "styles": {"arabic": {"decoration_layout": "elements"}},
    }
    cache = CaptionRenderCache()
    first = execute_request(data, cache=cache).to_dict()
    assert first["status"] == "complete", first
    cache.assets.clear()
    monkeypatch.setattr(api, "plan_scene", lambda _: pytest.fail("Group was fitted again"))
    second = execute_request(data, cache=cache).to_dict()
    assert second["status"] == "complete", second
    assert first["cues"] == second["cues"]
    assert first["assets"] == second["assets"]


def test_warm_cache_detects_pinned_font_change(tmp_path):
    font = tmp_path / "font.ttf"
    font.write_bytes(asset_path("fonts", "quran_font.ttf").read_bytes())
    data = fixture_request(tmp_path)
    data["assets"] = {
        "arabic": {
            "path": str(font),
            "sha256": hashlib.sha256(font.read_bytes()).hexdigest(),
            "license": "test",
            "attribution": "test",
        }
    }
    cache = CaptionRenderCache()
    assert execute_request(data, cache=cache).to_dict()["status"] == "complete"
    original_stat = font.stat()
    raw = bytearray(font.read_bytes())
    raw[-1] ^= 1
    font.write_bytes(raw)
    os.utime(font, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    result = execute_request(data, cache=cache).to_dict()
    assert result["status"] == "failed"
    assert result["cues"][0]["error"]["code"] == "changed_asset"


def test_pillow_word_spacing_keeps_whole_line_shaping_and_source_font(tmp_path):
    source = asset_path("fonts", "quran_font.ttf")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    with using_backend("pillow"):
        normal = ShapedFont(str(source), 30, "rtl")
        spaced = ShapedFont(str(source), 30, "rtl", word_spacing=12)
        text = "بِسْمِ ٱللَّهِ"
        assert spaced.backend == "pillow_raqm"
        assert spaced.advance(text) - normal.advance(text) == pytest.approx(12, abs=1)
        with Image.new("RGBA", (500, 200)) as a, Image.new("RGBA", (500, 200)) as b:
            normal.paint(a, text, 30, 100, "white")
            spaced.paint(b, text, 30, 100, "white")
            assert sum(a.getchannel("A").tobytes()) == pytest.approx(
                sum(b.getchannel("A").tobytes()), rel=0.01
            )
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_cached_pillow_font_faces_are_owned_by_each_worker():
    font = asset_path("fonts", "quran_font.ttf")

    def face(_):
        return shaped_font(font, 30)

    with ThreadPoolExecutor(max_workers=2) as workers:
        # Keep both workers alive together; neither can inherit a reused thread ID.
        import threading

        barrier = threading.Barrier(2)

        def separate(_):
            result = face(0)
            barrier.wait(timeout=10)
            return result

        a, b = list(workers.map(separate, range(2)))
    assert a is not b


def test_cache_evicts_by_memory_and_keeps_recent_values():
    disposed = []
    cache = RenderCache(3, max_bytes=10, dispose=disposed.append)
    cache.put("a", "first", size=4)
    cache.put("b", "second", size=4)
    assert cache.get("a") == "first"
    cache.put("c", "third", size=4)
    assert cache.get("b") is None and disposed == ["second"]
    assert cache.copy("a", str) == "first"
    cache.clear()
    assert len(cache) == 0


def test_capability_descriptors_match_selected_backend():
    native = capabilities("imagemagick")
    pillow = capabilities("pillow")
    assert pillow["default_render_backend"] == "pillow"
    assert native["style_contract"]["backend"]["active"] == (
        "wand_raqm" if runtime_identity()["native_raqm"] else "unavailable"
    )
    assert pillow["style_contract"]["backend"]["active"] == "pillow_raqm"
    assert not native["features"]["font_features"]
    assert pillow["style_contract"]["fields"]["word_spacing"]["backend_support"][
        "pillow_raqm"
    ]
