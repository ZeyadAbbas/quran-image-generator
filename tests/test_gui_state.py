from __future__ import annotations

import os
import random
import threading
import time
from dataclasses import replace
from hashlib import sha256

import pytest

from quran_image_generator.gui_state import (
    FormValidationError,
    JobCancelled,
    JobToken,
    PreviewArtifact,
    PreviewSnapshot,
    PreviewWorkflow,
    RevisionGate,
    SavedArtifact,
    SingleWorker,
    StalePreviewError,
    build_generation_request,
    normalize_translation_entries,
    translation_entry_label,
)
from quran_image_generator.models import (
    Chapter,
    GenerationRequest,
    GenerationResult,
    Passage,
    TranslationCatalog,
    TranslationResource,
    TranslationSelector,
    Verse,
)
from quran_image_generator.publishing import PublishTarget
from quran_image_generator.settings import TranslationSettings


def _passage(request: GenerationRequest) -> Passage:
    chapter = Chapter(request.chapter, f"Chapter {request.chapter}", 20)
    verses = tuple(
        Verse(number, f"{request.chapter}:{number}", ("word",), ())
        for number in range(request.starting_verse, request.ending_verse + 1)
    )
    return Passage(chapter, verses)


class FakeContentClient:
    def __init__(self) -> None:
        self.fetches: list[tuple[GenerationRequest, tuple[str, ...]]] = []

    def fetch_passage(self, request, resource_ids):
        key = (request, tuple(resource_ids))
        self.fetches.append(key)
        return _passage(request)


class FakeGenerator:
    def __init__(self) -> None:
        self.resolutions = 0
        self.renders = 0
        self.fail_render = False
        self.cancel_during_render: threading.Event | None = None

    def resolve_settings(self, settings):
        self.resolutions += 1
        resources = tuple(
            TranslationResource(
                item.selector.value,
                f"Translation {item.selector.value}",
                "Author",
                "English",
                "en",
                "1.0.0",
                "ltr",
            )
            for item in settings.translations
        )
        return replace(
            settings,
            translations=tuple(
                item.resolve(resource)
                for item, resource in zip(settings.translations, resources, strict=True)
            ),
        )

    def render_passage(self, passage, settings, *, destination):
        self.renders += 1
        if self.fail_render:
            self.fail_render = False
            raise RuntimeError("renderer failure")
        destination.write_bytes(
            b"png:" + settings.background_color.encode("ascii") + bytes([self.renders])
        )
        if self.cancel_during_render is not None:
            self.cancel_during_render.set()
            self.cancel_during_render = None
        return GenerationResult(destination, passage)


def _translation(resource_id: int) -> TranslationSettings:
    return TranslationSettings(
        TranslationSelector("key", str(resource_id)),
        None,
        18,
        configured_font=None,
    )


def _snapshot(revision, job_id, settings, request=None):
    request = request or GenerationRequest(1, 1, 1)
    return PreviewSnapshot(JobToken(job_id, revision, "preview"), request, settings)


def test_passage_form_reports_relevant_fields_and_uses_live_bounds():
    chapters = (Chapter(1, "Al-Fatihah", 7),)

    with pytest.raises(FormValidationError) as caught:
        build_generation_request(
            "bad",
            "0",
            "also bad",
            random_selection=False,
            chapters=chapters,
            rng=random.Random(1),
        )

    assert {item.field for item in caught.value.issues} == {
        "chapter",
        "starting verse",
        "ending verse",
    }


def test_translation_catalog_normalization_preserves_explicit_order_and_options():
    english = TranslationResource(
        "english", "English", "Author E", "English", "en", "1.0", "ltr"
    )
    french = TranslationResource(
        "french", "French", "Author F", "French", "fr", "1.0", "ltr"
    )
    entries = [
        {"key": "french", "font": "French.ttf", "font size": 17},
        {"key": "english"},
        {"key": "missing"},
    ]

    normalized = normalize_translation_entries(entries, (english, french))

    assert normalized == [
        {"key": "french", "font": "French.ttf", "font size": 17},
        {"key": "english"},
        {"key": "missing"},
    ]
    assert "French" in translation_entry_label(normalized[0], (english, french))
    assert translation_entry_label(normalized[2], (english, french)) == (
        "Unavailable: key=missing"
    )


def test_style_only_preview_reuses_resolved_resources_and_passage(
    settings_factory, tmp_path
):
    client = FakeContentClient()
    generator = FakeGenerator()
    settings = settings_factory(translations=(_translation(10), _translation(20)))
    workflow = PreviewWorkflow(
        generator, client, temporary_directory=tmp_path / "preview"
    )

    first = workflow.render_preview(_snapshot(0, 1, settings), threading.Event())
    styled = replace(settings, background_color="#123456", quran_font_size=30)
    second = workflow.render_preview(_snapshot(1, 2, styled), threading.Event())

    assert generator.resolutions == 1
    assert generator.renders == 2
    assert len(client.fetches) == 1
    assert first.resource_ids == second.resource_ids == ("10", "20")
    assert first.path.read_bytes() != second.path.read_bytes()


def test_request_or_ordered_translation_ids_change_content_cache_key(
    settings_factory, tmp_path
):
    client = FakeContentClient()
    generator = FakeGenerator()
    workflow = PreviewWorkflow(
        generator, client, temporary_directory=tmp_path / "preview"
    )
    settings = settings_factory(translations=(_translation(10), _translation(20)))
    reversed_settings = settings_factory(
        translations=(_translation(20), _translation(10))
    )

    workflow.render_preview(_snapshot(0, 1, settings), threading.Event())
    workflow.render_preview(
        _snapshot(1, 2, settings, GenerationRequest(1, 2, 2)),
        threading.Event(),
    )
    workflow.render_preview(_snapshot(2, 3, reversed_settings), threading.Event())

    assert [resource_ids for _request, resource_ids in client.fetches] == [
        ("10", "20"),
        ("10", "20"),
        ("20", "10"),
    ]


def test_successful_catalog_refresh_clears_passages_but_failure_preserves_them(
    settings_factory, tmp_path
):
    class RefreshingContentClient(FakeContentClient):
        def __init__(self) -> None:
            super().__init__()
            self.fail_refresh = False

        def list_chapters(self, *, refresh=False):
            assert refresh
            return (Chapter(1, "Al-Fatihah", 7),)

        def translation_catalog(self, *, refresh=False):
            assert refresh
            if self.fail_refresh:
                raise RuntimeError("catalog failure")
            return TranslationCatalog((), ())

    client = RefreshingContentClient()
    workflow = PreviewWorkflow(
        FakeGenerator(), client, temporary_directory=tmp_path / "preview"
    )
    settings = settings_factory()

    workflow.render_preview(_snapshot(0, 1, settings), threading.Event())
    client.fail_refresh = True
    with pytest.raises(RuntimeError, match="catalog failure"):
        workflow.load_catalogs(threading.Event())
    workflow.render_preview(_snapshot(0, 2, settings), threading.Event())
    assert len(client.fetches) == 1

    client.fail_refresh = False
    workflow.load_catalogs(threading.Event())
    workflow.render_preview(_snapshot(0, 3, settings), threading.Event())
    assert len(client.fetches) == 2


def test_failed_or_cancelled_render_does_not_cache_new_passage(
    settings_factory, tmp_path
):
    client = FakeContentClient()
    generator = FakeGenerator()
    workflow = PreviewWorkflow(
        generator, client, temporary_directory=tmp_path / "preview"
    )
    settings = settings_factory()
    generator.fail_render = True

    with pytest.raises(RuntimeError):
        workflow.render_preview(_snapshot(0, 1, settings), threading.Event())
    workflow.render_preview(_snapshot(0, 2, settings), threading.Event())
    assert len(client.fetches) == 2

    request = GenerationRequest(1, 2, 2)
    cancel_event = threading.Event()
    generator.cancel_during_render = cancel_event
    with pytest.raises(JobCancelled):
        workflow.render_preview(
            _snapshot(0, 3, settings, request),
            cancel_event,
        )
    workflow.render_preview(
        _snapshot(0, 4, settings, request),
        threading.Event(),
    )
    assert len(client.fetches) == 4


def test_save_copies_exact_preview_bytes_without_rendering(settings_factory, tmp_path):
    client = FakeContentClient()
    generator = FakeGenerator()
    workflow = PreviewWorkflow(
        generator, client, temporary_directory=tmp_path / "preview"
    )
    artifact = workflow.render_preview(
        _snapshot(0, 1, settings_factory()),
        threading.Event(),
    )
    render_count = generator.renders
    destination = tmp_path / "saved" / "exact.png"

    saved = workflow.save_preview(artifact, destination)

    assert destination.read_bytes() == artifact.path.read_bytes()
    assert saved.sha256 == artifact.sha256
    assert generator.renders == render_count
    assert len(client.fetches) == 1


def test_atomic_preview_save_preserves_existing_destination_on_replace_failure(
    monkeypatch, settings_factory, tmp_path
):
    client = FakeContentClient()
    generator = FakeGenerator()
    workflow = PreviewWorkflow(
        generator, client, temporary_directory=tmp_path / "preview"
    )
    artifact = workflow.render_preview(
        _snapshot(0, 1, settings_factory()),
        threading.Event(),
    )
    destination = tmp_path / "existing.png"
    destination.write_bytes(b"old")
    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(OSError()))

    with pytest.raises(OSError):
        workflow.save_preview(artifact, destination)

    assert destination.read_bytes() == b"old"
    assert list(tmp_path.glob(".existing.png.*.tmp")) == []


def test_atomic_preview_write_failure_removes_temporary_file(
    monkeypatch, settings_factory, tmp_path
):
    client = FakeContentClient()
    workflow = PreviewWorkflow(
        FakeGenerator(), client, temporary_directory=tmp_path / "preview"
    )
    artifact = workflow.render_preview(
        _snapshot(0, 1, settings_factory()),
        threading.Event(),
    )
    destination = tmp_path / "existing.png"
    destination.write_bytes(b"old")
    monkeypatch.setattr(
        os,
        "fsync",
        lambda *_args: (_ for _ in ()).throw(OSError("fsync failure")),
    )

    with pytest.raises(OSError, match="fsync failure"):
        workflow.save_preview(artifact, destination)

    assert destination.read_bytes() == b"old"
    assert list(tmp_path.glob(".existing.png.*.tmp")) == []


def test_cancelled_save_never_replaces_destination(settings_factory, tmp_path):
    client = FakeContentClient()
    generator = FakeGenerator()
    workflow = PreviewWorkflow(
        generator, client, temporary_directory=tmp_path / "preview"
    )
    artifact = workflow.render_preview(
        _snapshot(0, 1, settings_factory()),
        threading.Event(),
    )
    destination = tmp_path / "existing.png"
    destination.write_bytes(b"old")
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(JobCancelled):
        workflow.save_preview(artifact, destination, cancelled)

    assert destination.read_bytes() == b"old"
    assert list(tmp_path.glob(".existing.png.*.tmp")) == []


def test_revision_gate_rejects_late_results_and_modified_saved_files(
    settings_factory, tmp_path
):
    gate = RevisionGate()
    old_token = gate.begin("preview")
    gate.mark_changed()
    assert gate.finish(old_token) is False

    preview_path = tmp_path / "preview.png"
    preview_path.write_bytes(b"preview")
    settings = settings_factory()
    passage = _passage(GenerationRequest(1, 1, 1))
    digest = sha256(b"preview").hexdigest()
    artifact = PreviewArtifact(
        gate.revision,
        GenerationRequest(1, 1, 1),
        (),
        settings,
        passage,
        preview_path,
        digest,
    )
    current_token = gate.begin("preview")
    assert gate.accept_preview(current_token, artifact)
    saved_path = tmp_path / "saved.png"
    saved_path.write_bytes(b"preview")
    saved = SavedArtifact(gate.revision, saved_path, digest)
    gate.mark_saved(saved)
    assert gate.current_saved() == saved

    saved_path.write_bytes(b"changed")
    with pytest.raises(StalePreviewError, match="changed on disk"):
        gate.current_saved()


def test_publish_requires_a_distinct_unchanged_saved_copy(settings_factory, tmp_path):
    preview_path = tmp_path / "temporary-preview.png"
    preview_path.write_bytes(b"exact")
    digest = sha256(b"exact").hexdigest()
    preview = PreviewArtifact(
        0,
        GenerationRequest(1, 1, 1),
        (),
        settings_factory(),
        _passage(GenerationRequest(1, 1, 1)),
        preview_path,
        digest,
    )
    calls = []

    class Publisher:
        def publish(self, path, target):
            calls.append((path, target))

    with pytest.raises(StalePreviewError):
        PreviewWorkflow.publish_saved(
            preview,
            SavedArtifact(0, preview_path, digest),
            PublishTarget.POST,
            Publisher(),
        )

    saved_path = tmp_path / "saved.png"
    saved_path.write_bytes(b"exact")
    saved = SavedArtifact(0, saved_path, digest)
    PreviewWorkflow.publish_saved(preview, saved, PublishTarget.STORY, Publisher())
    assert calls == [(saved_path, PublishTarget.STORY)]

    saved_path.write_bytes(b"externally changed")
    with pytest.raises(StalePreviewError):
        PreviewWorkflow.publish_saved(preview, saved, PublishTarget.POST, Publisher())
    assert len(calls) == 1


def test_single_worker_is_bounded_daemon_and_cancellation_is_cooperative():
    worker = SingleWorker()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    token = JobToken(1, 0, "preview")

    def operation(_cancel_event):
        started.set()
        release.wait(timeout=2)
        finished.set()
        return "late"

    worker.submit(token, operation)
    assert started.wait(timeout=1)
    with pytest.raises(RuntimeError, match="already running"):
        worker.submit(JobToken(2, 0, "preview"), lambda _event: None)
    worker.cancel()
    release.set()
    assert finished.wait(timeout=1)

    result = ()
    for _ in range(1000):
        result = worker.poll()
        if result:
            break
        time.sleep(0.001)
    assert result and result[0].cancelled
    worker.close()


def test_worker_surfaces_actionable_stale_preview_errors():
    worker = SingleWorker()
    token = JobToken(1, 0, "save")

    def operation(_cancel_event):
        raise StalePreviewError("The current preview changed; refresh it.")

    worker.submit(token, operation)
    result = ()
    for _ in range(1000):
        result = worker.poll()
        if result:
            break
        time.sleep(0.001)

    assert result and result[0].message == ("The current preview changed; refresh it.")
    worker.close()


def test_worker_close_does_not_block_an_active_bounded_step():
    worker = SingleWorker()
    started = threading.Event()
    release = threading.Event()

    def operation(_cancel_event):
        started.set()
        release.wait(timeout=2)

    worker.submit(JobToken(1, 0, "preview"), operation)
    assert started.wait(timeout=1)
    before = time.monotonic()
    worker.close()
    assert time.monotonic() - before < 0.1
    release.set()
    for _ in range(1000):
        if not worker.is_alive:
            break
        time.sleep(0.001)
    assert not worker.is_alive
    assert worker.poll() == ()
