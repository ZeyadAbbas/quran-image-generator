import os
import subprocess
import sys
from pathlib import Path

import pytest

from quran_image_generator.content import TranslationSelectionError
from quran_image_generator.generator import QuranImageGenerator
from quran_image_generator.layout import LayoutOverflowError, TextMetrics
from quran_image_generator.models import (
    Chapter,
    GenerationRequest,
    Passage,
    TranslationResource,
    TranslationSelector,
    Verse,
    VerseTranslation,
)
from quran_image_generator.settings import Dimensions, TranslationSettings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_formats_inclusive_verse_keys():
    request = GenerationRequest(chapter=2, starting_verse=3, ending_verse=5)

    assert request.verse_keys() == ("2:3", "2:4", "2:5")


def test_generation_flow_uses_fakes(settings_factory):
    events = []
    passage = Passage(
        chapter=Chapter(1, "Al-Fatihah", 7),
        verses=(Verse(1, "1:1", ("بِسْمِ",), ()),),
    )

    class FakeContentClient:
        def fetch_passage(self, request, resource_ids):
            events.append(("fetch", request, resource_ids))
            return passage

    class FixedMeasurer:
        def measure(self, text, style):
            return TextMetrics(30, 10, 10, 0)

    class FakeRenderer:
        def render(self, image_layout, settings, destination):
            events.append(("render", destination))
            self.layout = image_layout
            return destination

    def fake_open(path):
        events.append(("open", path))

    settings = settings_factory(translations=())
    renderer = FakeRenderer()
    generator = QuranImageGenerator(
        settings,
        FakeContentClient(),
        FixedMeasurer(),
        renderer,
        image_opener=fake_open,
    )

    assert events == []
    request = GenerationRequest(1, 1, 1)
    result = generator.generate(request, open_output=True)

    expected_path = settings.output_path / "Al-Fatihah 1.png"
    assert result.path == expected_path
    assert result.passage is passage
    assert [
        (int(line.x), int(line.y), line.text) for line in renderer.layout.lines
    ] == [(135, 105, "بِسْمِ")]
    assert events == [
        ("fetch", request, ()),
        ("render", expected_path),
        ("open", expected_path),
    ]


def test_translation_selection_resolves_before_verses_and_flows_to_layout(
    settings_factory,
):
    events = []
    resource = TranslationResource(
        "131",
        "clearquran-with-tafsir",
        "The Clear Quran",
        "Dr. Mustafa Khattab",
        "English",
        "en",
    )
    passage = Passage(
        Chapter(1, "Al-Fatihah", 7),
        (Verse(1, "1:1", ("quran",), (VerseTranslation("131", "translation"),)),),
    )

    class FakeContentClient:
        def resolve_translations(self, selectors):
            events.append(("resolve", selectors))
            return (resource,)

        def fetch_passage(self, request, resource_ids):
            events.append(("fetch", resource_ids))
            return passage

    class FakeRenderer:
        def render(self, image_layout, settings, destination):
            events.append(("render", settings.translations[0].resource))
            return destination

    def fake_layout(received_passage, settings, measurer):
        translation = settings.translations[0]
        events.append(("layout", translation.resource_id, translation.font))
        assert received_passage is passage
        return object()

    configured = TranslationSettings(
        TranslationSelector("slug", "clearquran-with-tafsir"),
        None,
        18,
    )
    generator = QuranImageGenerator(
        settings_factory(translations=(configured,)),
        FakeContentClient(),
        object(),
        FakeRenderer(),
        layout_builder=fake_layout,
    )

    generator.generate(GenerationRequest(1, 1, 1))

    assert events == [
        ("resolve", (configured.selector,)),
        ("fetch", ("131",)),
        ("layout", "131", "Arial"),
        ("render", resource),
    ]


def test_invalid_translation_selection_stops_before_verse_fetch(settings_factory):
    class RejectingContentClient:
        def resolve_translations(self, selectors):
            raise TranslationSelectionError("choose an exact resource")

        def fetch_passage(self, request, resource_ids):
            pytest.fail("verse retrieval must not run after selection failure")

    class UnexpectedCall:
        def __getattr__(self, name):
            pytest.fail(f"{name} must not run after selection failure")

    configured = TranslationSettings(
        TranslationSelector("language", "en"),
        None,
        18,
    )
    generator = QuranImageGenerator(
        settings_factory(translations=(configured,)),
        RejectingContentClient(),
        UnexpectedCall(),
        UnexpectedCall(),
    )

    with pytest.raises(TranslationSelectionError, match="exact resource"):
        generator.generate(GenerationRequest(1, 1, 1))


def test_empty_passage_skips_layout_render_and_output_actions(settings_factory):
    class EmptyContentClient:
        def fetch_passage(self, request, resource_ids):
            return Passage(Chapter(request.chapter, "Test", 7), ())

    class UnexpectedCall:
        def __getattr__(self, name):
            pytest.fail(f"{name} should not be called for an empty passage")

    generator = QuranImageGenerator(
        settings_factory(),
        EmptyContentClient(),
        UnexpectedCall(),
        UnexpectedCall(),
        image_opener=lambda path: pytest.fail("image opener should not be called"),
    )

    result = generator.generate(GenerationRequest(1, 1, 1), open_output=True)

    assert result.path is None
    assert result.passage.verses == ()


def test_layout_overflow_stops_before_rendering(settings_factory):
    passage = Passage(
        chapter=Chapter(1, "Al-Fatihah", 7),
        verses=(Verse(1, "1:1", ("wide",), ()),),
    )

    class FakeContentClient:
        def fetch_passage(self, request, resource_ids):
            return passage

    class WideMeasurer:
        def measure(self, text, style):
            return TextMetrics(95, 10, 10, 0)

    class UnexpectedRenderer:
        def render(self, image_layout, settings, destination):
            pytest.fail("renderer must not run for an invalid layout")

    settings = settings_factory(
        resolution=Dimensions(100, 100),
        quran_max_width=100,
        quran_x_position=10,
    )
    generator = QuranImageGenerator(
        settings,
        FakeContentClient(),
        WideMeasurer(),
        UnexpectedRenderer(),
    )

    with pytest.raises(LayoutOverflowError, match="horizontal bounds"):
        generator.generate(GenerationRequest(1, 1, 1))


def test_core_imports_do_not_require_wand_or_instagram(tmp_path):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    script = (
        "import builtins; original = builtins.__import__; "
        "builtins.__import__ = lambda name, *a, **k: "
        "(_ for _ in ()).throw(ImportError(name)) "
        "if name.split('.')[0] in {'wand', 'instagrapi'} "
        "else original(name, *a, **k); "
        "from quran_image_generator import content, generator, layout, models"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
