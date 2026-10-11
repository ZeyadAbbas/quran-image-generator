"""Bundled Quran text and optional QuranEnc translation access."""

from __future__ import annotations

import hashlib
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any
from urllib.parse import quote

import requests

from .models import (
    Chapter,
    GenerationRequest,
    LanguageResource,
    Passage,
    TranslationCatalog,
    TranslationResource,
    TranslationSelector,
    Verse,
    VerseTranslation,
    validate_generation_request,
)

QURANENC_BASE_URL = "https://quranenc.com/api/v1"
TANZIL_TEXT_PATH = "assets/data/quran-uthmani-1.1.txt"
TANZIL_METADATA_PATH = "assets/data/quran-data-1.0.xml"
TANZIL_TEXT_SHA256 = (
    "bf4f57b968d03f4131c070b1e285da9be0e0a108a21c910e872801ca273312c8"
)
TRANSIENT_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class QuranDataError(RuntimeError):
    """Base error for bundled content and optional translations."""


class QuranDataIntegrityError(QuranDataError):
    """Bundled Tanzil data is missing, changed, or structurally invalid."""


class TranslationTransportError(QuranDataError):
    """QuranEnc could not be reached after bounded retries."""


class TranslationHttpError(QuranDataError):
    """QuranEnc returned an unsuccessful HTTP response."""

    def __init__(self, operation: str, status_code: int) -> None:
        self.operation = operation
        self.status_code = status_code
        super().__init__(f"{operation} failed with HTTP {status_code}")


class TranslationPayloadError(QuranDataError):
    """QuranEnc returned data that cannot be safely consumed."""


class TranslationSelectionError(QuranDataError):
    """A configured translation cannot be resolved unambiguously."""


@dataclass(frozen=True, slots=True)
class _BundledCorpus:
    chapters: tuple[Chapter, ...]
    verses: Mapping[tuple[int, int], str]


def _package_bytes(relative_path: str) -> bytes:
    try:
        return (
            resources.files("quran_image_generator")
            .joinpath(*relative_path.split("/"))
            .read_bytes()
        )
    except (FileNotFoundError, OSError) as error:
        raise QuranDataIntegrityError(
            f"bundled Quran data is missing: {relative_path}"
        ) from error


def _positive_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


@lru_cache(maxsize=1)
def _load_bundled_corpus() -> _BundledCorpus:
    text_bytes = _package_bytes(TANZIL_TEXT_PATH)
    digest = hashlib.sha256(text_bytes).hexdigest()
    if digest != TANZIL_TEXT_SHA256:
        raise QuranDataIntegrityError(
            "bundled Tanzil text failed its SHA-256 integrity check"
        )

    metadata_bytes = _package_bytes(TANZIL_METADATA_PATH)
    try:
        root = ET.fromstring(metadata_bytes)
    except ET.ParseError as error:
        raise QuranDataIntegrityError("bundled Tanzil metadata is invalid XML") from error

    suras = root.find("suras")
    if suras is None:
        raise QuranDataIntegrityError("bundled Tanzil metadata has no sura catalog")

    chapters: list[Chapter] = []
    expected_start = 0
    for expected_number, element in enumerate(suras.findall("sura"), start=1):
        number = _positive_integer(element.get("index"))
        count = _positive_integer(element.get("ayas"))
        name = (element.get("tname") or "").strip()
        try:
            start = int(element.get("start", ""))
        except ValueError as error:
            raise QuranDataIntegrityError(
                "bundled Tanzil metadata has an invalid start offset for "
                f"chapter {expected_number}"
            ) from error
        if number != expected_number or count is None or not name:
            raise QuranDataIntegrityError(
                f"bundled Tanzil metadata is invalid for chapter {expected_number}"
            )
        if start != expected_start:
            raise QuranDataIntegrityError(
                f"bundled Tanzil metadata has a discontinuity at chapter {number}"
            )
        chapters.append(Chapter(number, name, count, element.get("name", ""), element.get("ename", "")))
        expected_start += count

    if len(chapters) != 114 or expected_start != 6236:
        raise QuranDataIntegrityError(
            "bundled Tanzil metadata must describe 114 chapters and 6,236 verses"
        )

    try:
        decoded_text = text_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise QuranDataIntegrityError("bundled Tanzil text is not valid UTF-8") from error

    verses: dict[tuple[int, int], str] = {}
    for line_number, raw_line in enumerate(decoded_text.splitlines(), start=1):
        if not raw_line or raw_line.startswith("#"):
            continue
        fields = raw_line.split("|", 2)
        if len(fields) != 3:
            raise QuranDataIntegrityError(
                f"bundled Tanzil text has an invalid record on line {line_number}"
            )
        chapter_number = _positive_integer(fields[0])
        verse_number = _positive_integer(fields[1])
        verse_text = fields[2]
        if chapter_number is None or verse_number is None or not verse_text.strip():
            raise QuranDataIntegrityError(
                f"bundled Tanzil text has an invalid record on line {line_number}"
            )
        key = (chapter_number, verse_number)
        if key in verses:
            raise QuranDataIntegrityError(
                f"bundled Tanzil text duplicates verse {chapter_number}:{verse_number}"
            )
        verses[key] = verse_text

    if len(verses) != 6236:
        raise QuranDataIntegrityError(
            "bundled Tanzil text must contain exactly 6,236 verses"
        )
    for chapter in chapters:
        for verse_number in range(1, chapter.verses_count + 1):
            if (chapter.number, verse_number) not in verses:
                raise QuranDataIntegrityError(
                    f"bundled Tanzil text is missing verse {chapter.number}:{verse_number}"
                )

    return _BundledCorpus(tuple(chapters), verses)


def _required_string(item: Mapping[str, Any], field: str, context: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise TranslationPayloadError(f"{context} has an invalid {field!r} field")
    return value.strip()


class QuranDataClient:
    """Read bundled Arabic locally and retrieve selected QuranEnc translations."""

    _translation_catalog_cache: TranslationCatalog | None = None
    _translation_cache: dict[tuple[str, int], tuple[str, ...]] = {}
    _cache_lock = threading.RLock()

    def __init__(
        self,
        *,
        session: requests.Session | Any | None = None,
        timeout: float = 20.0,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._session = requests.Session() if session is None else session
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._sleep = sleep

    @classmethod
    def clear_translation_catalog_cache(cls) -> None:
        with cls._cache_lock:
            cls._translation_catalog_cache = None
            cls._translation_cache.clear()

    @classmethod
    def clear_chapter_catalog_cache(cls) -> None:
        _load_bundled_corpus.cache_clear()

    def list_chapters(self, *, refresh: bool = False) -> tuple[Chapter, ...]:
        """Return the complete bundled Tanzil chapter catalog."""

        if refresh:
            self.clear_chapter_catalog_cache()
        return _load_bundled_corpus().chapters

    def get_chapter(self, number: int) -> Chapter:
        """Return one bundled chapter or reject an invalid number."""

        if isinstance(number, bool) or not isinstance(number, int):
            raise ValueError("chapter number must be a positive whole number")
        chapters = self.list_chapters()
        if number < 1 or number > len(chapters):
            raise ValueError(f"chapter number must be between 1 and {len(chapters)}")
        return chapters[number - 1]

    def _get_json(self, path: str, operation: str) -> Any:
        url = f"{QURANENC_BASE_URL}/{path.lstrip('/')}"
        last_error: requests.RequestException | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._session.get(url, timeout=self._timeout)
            except requests.RequestException as error:
                last_error = error
                if attempt == self._max_attempts:
                    break
                self._sleep(float(2 ** (attempt - 1)))
                continue

            status_code = int(response.status_code)
            if status_code in TRANSIENT_STATUS_CODES and attempt < self._max_attempts:
                self._sleep(float(2 ** (attempt - 1)))
                continue
            if status_code < 200 or status_code >= 300:
                raise TranslationHttpError(operation, status_code)
            try:
                return response.json()
            except ValueError as error:
                raise TranslationPayloadError(
                    f"{operation} returned invalid JSON"
                ) from error

        raise TranslationTransportError(
            f"{operation} could not reach QuranEnc after {self._max_attempts} attempts"
        ) from last_error

    def translation_catalog(self, *, refresh: bool = False) -> TranslationCatalog:
        """Return a cached, validated QuranEnc translation catalog."""

        with self._cache_lock:
            if not refresh and self._translation_catalog_cache is not None:
                return self._translation_catalog_cache

        payload = self._get_json(
            "translations/list?localization=en", "loading the translation catalog"
        )
        if not isinstance(payload, Mapping):
            raise TranslationPayloadError(
                "translation catalog response must be an object"
            )
        raw_resources = payload.get("translations")
        if not isinstance(raw_resources, list):
            raise TranslationPayloadError(
                "translation catalog response must contain a translations list"
            )

        resources_found: list[TranslationResource] = []
        seen_keys: set[str] = set()
        language_counts: dict[str, int] = {}
        directions: dict[str, str] = {}
        for index, raw_resource in enumerate(raw_resources, start=1):
            context = f"translation catalog item {index}"
            if not isinstance(raw_resource, Mapping):
                raise TranslationPayloadError(f"{context} must be an object")
            key = _required_string(raw_resource, "key", context)
            language_code = _required_string(
                raw_resource, "language_iso_code", context
            ).casefold()
            title = _required_string(raw_resource, "title", context)
            description = _required_string(raw_resource, "description", context)
            version = _required_string(raw_resource, "version", context)
            direction = _required_string(raw_resource, "direction", context).casefold()
            if direction not in {"ltr", "rtl"}:
                raise TranslationPayloadError(
                    f"{context} has an unsupported text direction"
                )
            normalized_key = key.casefold()
            if normalized_key in seen_keys:
                raise TranslationPayloadError(
                    f"translation key {key!r} is duplicated"
                )
            seen_keys.add(normalized_key)
            language_counts[language_code] = language_counts.get(language_code, 0) + 1
            directions.setdefault(language_code, direction)
            resources_found.append(
                TranslationResource(
                    resource_id=key,
                    name=title,
                    description=description,
                    language_name=language_code.upper(),
                    language_code=language_code,
                    version=version,
                    direction=direction,
                )
            )

        if not resources_found:
            raise TranslationPayloadError("translation catalog is empty")

        resources_found.sort(
            key=lambda item: (
                item.language_code.casefold(),
                item.name.casefold(),
                item.resource_id.casefold(),
            )
        )
        languages = tuple(
            LanguageResource(
                resource_id=index,
                name=code.upper(),
                native_name=None,
                iso_code=code,
                direction=directions[code],
                translations_count=count,
            )
            for index, (code, count) in enumerate(
                sorted(language_counts.items()), start=1
            )
        )
        catalog = TranslationCatalog(tuple(resources_found), languages)
        with self._cache_lock:
            self.__class__._translation_catalog_cache = catalog
        return catalog

    @staticmethod
    def _resource_label(resource: TranslationResource) -> str:
        return f"key={resource.resource_id} ({resource.display_name})"

    def resolve_translations(
        self,
        selectors: Sequence[TranslationSelector],
        *,
        refresh: bool = False,
    ) -> tuple[TranslationResource, ...]:
        """Resolve each configured selector to exactly one QuranEnc resource."""

        catalog = self.translation_catalog(refresh=refresh)
        selected: list[TranslationResource] = []
        for selector in selectors:
            if selector.kind == "key":
                matches = tuple(
                    resource
                    for resource in catalog.resources
                    if resource.resource_id.casefold() == selector.value.casefold()
                )
            else:
                normalized = selector.value.casefold()
                matches = tuple(
                    resource
                    for resource in catalog.resources
                    if normalized
                    in {
                        resource.language_code.casefold(),
                        resource.language_name.casefold(),
                    }
                )
            if not matches:
                raise TranslationSelectionError(
                    f"no translation matches {selector.label}"
                )
            if len(matches) > 1:
                choices = ", ".join(self._resource_label(item) for item in matches[:5])
                raise TranslationSelectionError(
                    f"{selector.label} matches multiple translations; choose an exact "
                    f"key: {choices}"
                )
            resource = matches[0]
            if any(
                item.resource_id.casefold() == resource.resource_id.casefold()
                for item in selected
            ):
                raise TranslationSelectionError(
                    f"translation key {resource.resource_id} is already selected"
                )
            selected.append(resource)
        return tuple(selected)

    def _translation_for_chapter(
        self, resource_key: str, chapter: Chapter
    ) -> tuple[str, ...]:
        cache_key = (resource_key.casefold(), chapter.number)
        with self._cache_lock:
            cached = self._translation_cache.get(cache_key)
        if cached is not None:
            return cached

        safe_key = quote(resource_key, safe="")
        payload = self._get_json(
            f"translation/sura/{safe_key}/{chapter.number}",
            f"loading translation {resource_key!r} for chapter {chapter.number}",
        )
        if not isinstance(payload, Mapping):
            raise TranslationPayloadError("translation response must be an object")
        records = payload.get("result")
        if not isinstance(records, list):
            raise TranslationPayloadError(
                "translation response must contain a result list"
            )

        by_verse: dict[int, str] = {}
        for index, record in enumerate(records, start=1):
            context = f"translation result item {index}"
            if not isinstance(record, Mapping):
                raise TranslationPayloadError(f"{context} must be an object")
            sura = _positive_integer(record.get("sura"))
            aya = _positive_integer(record.get("aya"))
            translation = record.get("translation")
            if sura != chapter.number or aya is None:
                raise TranslationPayloadError(
                    f"{context} does not identify a verse in chapter {chapter.number}"
                )
            if aya in by_verse:
                raise TranslationPayloadError(
                    f"translation response duplicates verse {chapter.number}:{aya}"
                )
            if not isinstance(translation, str) or not translation.strip():
                raise TranslationPayloadError(
                    f"translation response has no text for verse {chapter.number}:{aya}"
                )
            by_verse[aya] = translation

        expected = set(range(1, chapter.verses_count + 1))
        if set(by_verse) != expected:
            raise TranslationPayloadError(
                f"translation {resource_key!r} must contain every verse in chapter "
                f"{chapter.number}"
            )
        translated = tuple(
            by_verse[number] for number in range(1, chapter.verses_count + 1)
        )
        with self._cache_lock:
            self.__class__._translation_cache[cache_key] = translated
        return translated

    def fetch_passage(
        self,
        request: GenerationRequest,
        translation_resource_ids: Sequence[str],
    ) -> Passage:
        """Return a passage from bundled Arabic plus optional translations."""

        chapter = validate_generation_request(request, self.list_chapters())
        corpus = _load_bundled_corpus()
        resource_keys = tuple(translation_resource_ids)
        if len({item.casefold() for item in resource_keys}) != len(resource_keys):
            raise TranslationSelectionError("translation keys must not be duplicated")

        translated_chapters = {
            key: self._translation_for_chapter(key, chapter) for key in resource_keys
        }
        verses = tuple(
            Verse(
                number=number,
                key=f"{chapter.number}:{number}",
                words=tuple(corpus.verses[(chapter.number, number)].split()),
                translations=tuple(
                    VerseTranslation(
                        resource_id=key,
                        text=translated_chapters[key][number - 1],
                    )
                    for key in resource_keys
                ),
            )
            for number in range(request.starting_verse, request.ending_verse + 1)
        )
        return Passage(chapter, verses)
