"""Headless state and workflow services used by the desktop GUI.

This module deliberately has no tkinter dependency.  It keeps validation,
revision gating, background work, caching, and exact-byte saves testable on
servers and in the container build.
"""

from __future__ import annotations

import hashlib
import os
import queue
import shutil
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, TypeVar

from .content import (
    QuranDataError,
    TranslationHttpError,
    TranslationPayloadError,
    TranslationTransportError,
)
from .generator import QuranImageGenerator, default_output_path
from .layout import LayoutOverflowError
from .models import (
    Chapter,
    GenerationRequest,
    InvalidVerseRangeError,
    Passage,
    RandomSource,
    TranslationCatalog,
    TranslationResource,
    random_generation_request,
    validate_generation_request,
)
from .publishing import Publisher, PublishingError, PublishTarget
from .settings import Settings, SettingsValidationError

README_URL = "https://github.com/ZeyadAbbas/quran-image-generator#readme"


@dataclass(frozen=True, slots=True)
class FormIssue:
    field: str
    message: str


class FormValidationError(ValueError):
    def __init__(self, issues: Sequence[FormIssue]):
        self.issues = tuple(issues)
        super().__init__("\n".join(f"{item.field}: {item.message}" for item in issues))


def _positive_integer(value: object, field: str) -> tuple[int | None, FormIssue | None]:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = 0
    if isinstance(value, bool) or parsed < 1:
        return None, FormIssue(field, "must be a positive whole number")
    return parsed, None


def build_generation_request(
    chapter: object,
    starting_verse: object,
    ending_verse: object,
    *,
    random_selection: bool,
    chapters: Sequence[Chapter],
    rng: RandomSource,
) -> GenerationRequest:
    """Validate passage controls against the bundled chapter bounds."""

    if random_selection:
        try:
            return random_generation_request(chapters, rng)
        except InvalidVerseRangeError as error:
            raise FormValidationError((FormIssue("passage", str(error)),)) from None

    parsed: list[int] = []
    issues: list[FormIssue] = []
    for value, field in (
        (chapter, "chapter"),
        (starting_verse, "starting verse"),
        (ending_verse, "ending verse"),
    ):
        number, issue = _positive_integer(value, field)
        if issue is not None:
            issues.append(issue)
        else:
            parsed.append(number or 1)
    if issues:
        raise FormValidationError(issues)
    try:
        request = GenerationRequest(*parsed)
        validate_generation_request(request, chapters)
    except InvalidVerseRangeError as error:
        raise FormValidationError((FormIssue("passage", str(error)),)) from None
    return request


def translation_label(resource: TranslationResource) -> str:
    """Return a compact catalog label that still exposes exact identity."""

    language = resource.language_code or resource.language_name
    return (
        f"KEY {resource.resource_id} · {language} · "
        f"{resource.display_name} · v{resource.version}"
    )


def matching_translation_resource(
    entry: Mapping[str, Any],
    resources: Sequence[TranslationResource],
) -> TranslationResource | None:
    """Resolve one GUI/config selector only when it has one catalog match."""

    matches: list[TranslationResource] = []
    for resource in resources:
        if (
            "key" in entry
            and str(entry["key"]).casefold() == resource.resource_id.casefold()
        ):
            matches.append(resource)
        elif "language" in entry and str(entry["language"]).casefold() in {
            resource.language_code.casefold(),
            resource.language_name.casefold(),
        }:
            matches.append(resource)
    return matches[0] if len(matches) == 1 else None


def normalize_translation_entries(
    entries: Sequence[object],
    resources: Sequence[TranslationResource],
) -> list[dict[str, Any]]:
    """Preserve configured order while upgrading selectors to exact keys."""

    normalized_entries: list[dict[str, Any]] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, Mapping):
            continue
        entry = dict(raw_entry)
        resource = matching_translation_resource(entry, resources)
        if resource is None:
            normalized_entries.append(entry)
            continue
        normalized: dict[str, Any] = {"key": resource.resource_id}
        for option in ("font", "font size"):
            if option in entry:
                normalized[option] = entry[option]
        normalized_entries.append(normalized)
    return normalized_entries


def translation_entry_label(
    entry: Mapping[str, Any],
    resources: Sequence[TranslationResource],
) -> str:
    """Describe an ordered selection, including selectors absent from the catalog."""

    resource = matching_translation_resource(entry, resources)
    if resource is not None:
        return translation_label(resource)
    for selector in ("key", "language"):
        if selector in entry:
            return f"Unavailable: {selector}={entry[selector]}"
    return "Unavailable translation selector"


@dataclass(frozen=True, slots=True)
class JobToken:
    job_id: int
    revision: int
    kind: str


@dataclass(frozen=True, slots=True)
class PreviewSnapshot:
    token: JobToken
    request: GenerationRequest
    settings: Settings


@dataclass(frozen=True, slots=True)
class ContentKey:
    request: GenerationRequest
    resource_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreviewArtifact:
    revision: int
    request: GenerationRequest
    resource_ids: tuple[str, ...]
    settings: Settings
    passage: Passage
    path: Path
    sha256: str

    @property
    def suggested_path(self) -> Path:
        return default_output_path(self.passage, self.settings.output_path)


@dataclass(frozen=True, slots=True)
class SavedArtifact:
    revision: int
    path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    chapters: tuple[Chapter, ...]
    translations: TranslationCatalog
    warning: str | None = None


class StalePreviewError(RuntimeError):
    """The requested output action is not valid for the current form."""


class JobCancelled(RuntimeError):
    """Cooperative cancellation between bounded background stages."""


class RevisionGate:
    """Accept results only for the latest unchanged form revision."""

    def __init__(self) -> None:
        self._revision = 0
        self._next_job_id = 1
        self._active: JobToken | None = None
        self._preview: PreviewArtifact | None = None
        self._saved: SavedArtifact | None = None
        self._closed = False

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def active(self) -> JobToken | None:
        return self._active

    @property
    def preview_is_current(self) -> bool:
        return (
            not self._closed
            and self._preview is not None
            and self._preview.revision == self._revision
            and self._preview.path.is_file()
        )

    @property
    def saved_is_current(self) -> bool:
        saved = self._saved
        preview = self._preview
        return (
            self.preview_is_current
            and saved is not None
            and preview is not None
            and saved.revision == self._revision
            and saved.sha256 == preview.sha256
            and saved.path.is_file()
        )

    def mark_changed(self) -> int:
        if not self._closed:
            self._revision += 1
            self._saved = None
        return self._revision

    def begin(self, kind: str) -> JobToken:
        if self._closed:
            raise RuntimeError("the GUI session is closed")
        if self._active is not None:
            raise RuntimeError("another operation is already running")
        token = JobToken(self._next_job_id, self._revision, kind)
        self._next_job_id += 1
        self._active = token
        return token

    def finish(self, token: JobToken) -> bool:
        if token != self._active:
            return False
        self._active = None
        return not self._closed and token.revision == self._revision

    def accept_preview(self, token: JobToken, artifact: PreviewArtifact) -> bool:
        current = self.finish(token)
        if not current or artifact.revision != self._revision:
            return False
        self._preview = artifact
        self._saved = None
        return True

    def current_preview(self) -> PreviewArtifact:
        if not self.preview_is_current or self._preview is None:
            raise StalePreviewError(
                "Generate or refresh the preview after the latest changes."
            )
        return self._preview

    def mark_saved(self, saved: SavedArtifact) -> None:
        preview = self.current_preview()
        if (
            saved.revision != self._revision
            or saved.sha256 != preview.sha256
            or saved.path.resolve(strict=False) == preview.path.resolve(strict=False)
        ):
            raise StalePreviewError(
                "The saved image does not match the current preview."
            )
        self._saved = saved

    def current_saved(self) -> SavedArtifact:
        preview = self.current_preview()
        saved = self._saved
        if (
            saved is None
            or saved.revision != self._revision
            or not saved.path.is_file()
        ):
            raise StalePreviewError(
                "Save the current preview before opening or publishing it."
            )
        if _file_sha256(saved.path) != saved.sha256 or saved.sha256 != preview.sha256:
            raise StalePreviewError(
                "The saved image changed on disk; save the current preview again."
            )
        return saved

    def close(self) -> None:
        self._closed = True
        self._active = None
        self._preview = None
        self._saved = None


T = TypeVar("T")
WorkerOperation = Callable[[threading.Event], T]


@dataclass(frozen=True, slots=True)
class _WorkerTask:
    token: JobToken
    operation: WorkerOperation[Any]
    cancel_event: threading.Event


@dataclass(frozen=True, slots=True)
class WorkerResult:
    token: JobToken
    value: object | None = None
    message: str | None = None
    cancelled: bool = False


def safe_error_message(error: BaseException) -> str:
    """Expose known user-safe failures without leaking arbitrary exception data."""

    safe_types = (
        FormValidationError,
        InvalidVerseRangeError,
        LayoutOverflowError,
        QuranDataError,
        SettingsValidationError,
        PublishingError,
        StalePreviewError,
    )
    if isinstance(error, safe_types):
        return str(error)
    if isinstance(error, (FileNotFoundError, PermissionError)):
        return str(error)
    return "The operation failed unexpectedly. Please verify the settings and retry."


class SingleWorker:
    """One bounded daemon worker; callers poll plain ``WorkerResult`` values."""

    _STOP = object()

    def __init__(self) -> None:
        self._tasks: queue.Queue[_WorkerTask | object] = queue.Queue(maxsize=1)
        self._results: queue.SimpleQueue[WorkerResult] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._current_cancel: threading.Event | None = None
        self._busy = False
        self._closed = False
        self._thread = threading.Thread(
            target=self._run,
            name="quran-image-generator-gui-worker",
            daemon=True,
        )
        self._thread.start()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def submit(self, token: JobToken, operation: WorkerOperation[Any]) -> None:
        cancel_event = threading.Event()
        with self._lock:
            if self._closed:
                raise RuntimeError("the background worker is closed")
            if self._busy:
                raise RuntimeError("another operation is already running")
            self._busy = True
            self._current_cancel = cancel_event
        self._tasks.put_nowait(_WorkerTask(token, operation, cancel_event))

    def cancel(self) -> None:
        with self._lock:
            if self._current_cancel is not None:
                self._current_cancel.set()

    def poll(self) -> tuple[WorkerResult, ...]:
        results: list[WorkerResult] = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except queue.Empty:
                return tuple(results)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._current_cancel is not None:
                self._current_cancel.set()
        try:
            self._tasks.put_nowait(self._STOP)
        except queue.Full:
            pass

    def _run(self) -> None:
        while True:
            task = self._tasks.get()
            if task is self._STOP:
                return
            assert isinstance(task, _WorkerTask)
            try:
                if task.cancel_event.is_set():
                    raise JobCancelled
                value = task.operation(task.cancel_event)
                cancelled = task.cancel_event.is_set()
                result = WorkerResult(
                    task.token,
                    value=None if cancelled else value,
                    cancelled=cancelled,
                )
            except JobCancelled:
                result = WorkerResult(task.token, cancelled=True)
            except BaseException as error:  # keep the daemon alive after one job
                result = WorkerResult(task.token, message=safe_error_message(error))
            with self._lock:
                self._busy = False
                self._current_cancel = None
                closed = self._closed
            if not closed:
                self._results.put(result)
            if closed:
                return


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PreviewWorkflow:
    """Shared-service preview/cache/save/publish workflow with no GUI objects."""

    def __init__(
        self,
        generator: QuranImageGenerator,
        content_client: Any,
        *,
        temporary_directory: str | Path | None = None,
    ) -> None:
        self._generator = generator
        self._content_client = content_client
        self._temporary_owner: tempfile.TemporaryDirectory[str] | None = None
        if temporary_directory is None:
            self._temporary_owner = tempfile.TemporaryDirectory(prefix="qig-preview-")
            self._temporary_directory = Path(self._temporary_owner.name)
        else:
            self._temporary_directory = Path(temporary_directory)
            self._temporary_directory.mkdir(parents=True, exist_ok=True)
        self._passages: dict[ContentKey, Passage] = {}
        self._resources: dict[
            tuple[tuple[str, str], ...], tuple[TranslationResource, ...]
        ] = {}
        self._closed = False

    @staticmethod
    def _check_cancel(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise JobCancelled

    @staticmethod
    def _selector_key(settings: Settings) -> tuple[tuple[str, str], ...]:
        return tuple(
            (item.selector.kind, item.selector.value) for item in settings.translations
        )

    def load_catalogs(self, cancel_event: threading.Event) -> CatalogSnapshot:
        self._check_cancel(cancel_event)
        chapters = tuple(self._content_client.list_chapters(refresh=True))
        self._check_cancel(cancel_event)
        warning = None
        try:
            translations = self._content_client.translation_catalog(refresh=True)
        except (
            TranslationHttpError,
            TranslationPayloadError,
            TranslationTransportError,
        ) as error:
            translations = TranslationCatalog((), ())
            warning = (
                f"Translations are unavailable: {error}. "
                "Arabic-only generation remains available."
            )
        self._check_cancel(cancel_event)
        self._resources.clear()
        self._passages.clear()
        return CatalogSnapshot(chapters, translations, warning)

    def _resolve_settings(
        self, settings: Settings, cancel_event: threading.Event
    ) -> Settings:
        selector_key = self._selector_key(settings)
        resources = self._resources.get(selector_key)
        if resources is None:
            runtime_settings = self._generator.resolve_settings(settings)
            self._check_cancel(cancel_event)
            resources = tuple(
                item.resource
                for item in runtime_settings.translations
                if item.resource is not None
            )
            if len(resources) != len(runtime_settings.translations):
                raise RuntimeError(
                    "translation resolution returned incomplete resources"
                )
            self._resources[selector_key] = resources
            return runtime_settings
        return replace(
            settings,
            translations=tuple(
                item.resolve(resource)
                for item, resource in zip(settings.translations, resources, strict=True)
            ),
        )

    def render_preview(
        self, snapshot: PreviewSnapshot, cancel_event: threading.Event
    ) -> PreviewArtifact:
        if self._closed:
            raise JobCancelled
        self._check_cancel(cancel_event)
        settings = self._resolve_settings(snapshot.settings, cancel_event)
        resource_ids = tuple(item.resource_id for item in settings.translations)
        content_key = ContentKey(snapshot.request, resource_ids)
        passage = self._passages.get(content_key)
        fetched_passage = passage is None
        if passage is None:
            passage = self._content_client.fetch_passage(
                snapshot.request,
                resource_ids,
            )
            self._check_cancel(cancel_event)
        destination = self._temporary_directory / (
            f"preview-{snapshot.token.job_id}-{snapshot.token.revision}.png"
        )
        try:
            result = self._generator.render_passage(
                passage,
                settings,
                destination=destination,
            )
            self._check_cancel(cancel_event)
            if result.path is None or not result.path.is_file():
                raise RuntimeError("the renderer did not produce a preview")
            if fetched_passage:
                self._passages[content_key] = passage
            return PreviewArtifact(
                revision=snapshot.token.revision,
                request=snapshot.request,
                resource_ids=resource_ids,
                settings=settings,
                passage=passage,
                path=result.path,
                sha256=_file_sha256(result.path),
            )
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    @staticmethod
    def discard_preview(artifact: PreviewArtifact) -> None:
        artifact.path.unlink(missing_ok=True)

    @staticmethod
    def save_preview(
        artifact: PreviewArtifact,
        destination: str | Path,
        cancel_event: threading.Event | None = None,
    ) -> SavedArtifact:
        target = Path(destination).expanduser().resolve(strict=False)
        if target == artifact.path.resolve(strict=False):
            raise StalePreviewError(
                "Choose a saved output path outside the managed preview location."
            )
        if (
            not artifact.path.is_file()
            or _file_sha256(artifact.path) != artifact.sha256
        ):
            raise StalePreviewError(
                "The current preview is missing or changed; refresh it."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                with artifact.path.open("rb") as preview_file:
                    shutil.copyfileobj(preview_file, temporary_file)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            if cancel_event is not None and cancel_event.is_set():
                raise JobCancelled
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return SavedArtifact(artifact.revision, target, artifact.sha256)

    @staticmethod
    def publish_saved(
        preview: PreviewArtifact,
        saved: SavedArtifact,
        target: PublishTarget,
        publisher: Publisher,
    ) -> None:
        if (
            preview.revision != saved.revision
            or preview.sha256 != saved.sha256
            or saved.path.resolve(strict=False) == preview.path.resolve(strict=False)
            or not saved.path.is_file()
            or _file_sha256(saved.path) != saved.sha256
        ):
            raise StalePreviewError(
                "Save the unchanged current preview before publishing it."
            )
        publisher.publish(saved.path, target)

    def close(self) -> None:
        self._closed = True
        if self._temporary_owner is not None:
            try:
                self._temporary_owner.cleanup()
            except OSError:
                pass
