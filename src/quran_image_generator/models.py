"""Small immutable values shared by the generator's core services."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

TranslationSelectorKind = Literal["key", "language"]


class InvalidVerseRangeError(ValueError):
    """A passage request cannot be satisfied by the bundled Quran data."""


class RandomSource(Protocol):
    """The small random API needed for deterministic passage selection."""

    def randrange(self, stop: int, /) -> int: ...

    def randint(self, start: int, stop: int, /) -> int: ...


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    chapter: int
    starting_verse: int
    ending_verse: int

    def __post_init__(self) -> None:
        for label, value in (
            ("chapter", self.chapter),
            ("starting verse", self.starting_verse),
            ("ending verse", self.ending_verse),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise InvalidVerseRangeError(
                    f"{label} must be a positive whole number"
                )
        if self.starting_verse > self.ending_verse:
            raise InvalidVerseRangeError(
                "ending verse must be greater than or equal to starting verse"
            )

    def verse_keys(self) -> tuple[str, ...]:
        """Return the requested verse keys in their original order."""

        return tuple(
            f"{self.chapter}:{verse_number}"
            for verse_number in range(self.starting_verse, self.ending_verse + 1)
        )


@dataclass(frozen=True, slots=True)
class Chapter:
    """Chapter metadata loaded from the bundled Tanzil data."""

    number: int
    name_simple: str
    verses_count: int


def validate_generation_request(
    request: GenerationRequest, chapters: Sequence[Chapter]
) -> Chapter:
    """Return matching metadata or reject a request outside the Quran."""

    chapter = next(
        (item for item in chapters if item.number == request.chapter),
        None,
    )
    if chapter is None:
        raise InvalidVerseRangeError(
            f"chapter {request.chapter} is not available in the bundled Quran data"
        )
    if request.ending_verse > chapter.verses_count:
        raise InvalidVerseRangeError(
            f"ending verse must be between {request.starting_verse} and "
            f"{chapter.verses_count} for chapter {chapter.number}"
        )
    return chapter


def random_generation_request(
    chapters: Sequence[Chapter], rng: RandomSource
) -> GenerationRequest:
    """Choose a short valid request from an injected random source."""

    available = tuple(chapters)
    if not available:
        raise InvalidVerseRangeError(
            "the bundled Quran data did not contain any chapters"
        )
    chapter = available[rng.randrange(len(available))]
    starting_verse = rng.randint(1, chapter.verses_count)
    remaining = chapter.verses_count - starting_verse + 1
    length = rng.randint(1, min(5, remaining))
    return GenerationRequest(
        chapter.number,
        starting_verse,
        starting_verse + length - 1,
    )


@dataclass(frozen=True, slots=True)
class TranslationSelector:
    """One configurable way to select a QuranEnc translation."""

    kind: TranslationSelectorKind
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise ValueError("translation selector value cannot be blank")
        if self.kind not in {"key", "language"}:
            raise ValueError(f"unsupported translation selector kind: {self.kind}")
        object.__setattr__(self, "value", normalized)

    @property
    def label(self) -> str:
        return f"{self.kind}={self.value}"


@dataclass(frozen=True, slots=True)
class LanguageResource:
    """A language derived from the QuranEnc translation catalog."""

    resource_id: int
    name: str
    native_name: str | None
    iso_code: str
    direction: str
    translations_count: int | None


@dataclass(frozen=True, slots=True)
class TranslationResource:
    """The exact QuranEnc translation identity used for verse requests."""

    resource_id: str
    name: str
    description: str
    language_name: str
    language_code: str
    version: str
    direction: str

    @property
    def display_name(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class TranslationCatalog:
    """One immutable snapshot of the QuranEnc translation catalog."""

    resources: tuple[TranslationResource, ...]
    languages: tuple[LanguageResource, ...]


@dataclass(frozen=True, slots=True)
class VerseTranslation:
    resource_id: str
    text: str


@dataclass(frozen=True, slots=True)
class Verse:
    number: int
    key: str
    words: tuple[str, ...]
    translations: tuple[VerseTranslation, ...]


@dataclass(frozen=True, slots=True)
class Passage:
    chapter: Chapter
    verses: tuple[Verse, ...]

    @property
    def chapter_number(self) -> int:
        """Compatibility alias for callers migrating to ``passage.chapter``."""

        return self.chapter.number

    @property
    def chapter_name(self) -> str:
        """Compatibility alias for callers migrating to ``passage.chapter``."""

        return self.chapter.name_simple


@dataclass(frozen=True, slots=True)
class GenerationResult:
    path: Path | None
    passage: Passage
