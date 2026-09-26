"""Small immutable values shared by the generator's core services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TranslationSelectorKind = Literal["id", "slug", "language"]


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    chapter: int
    starting_verse: int
    ending_verse: int

    def verse_keys(self) -> tuple[str, ...]:
        """Return the requested Quran.com verse keys in their original order."""

        return tuple(
            f"{self.chapter}:{verse_number}"
            for verse_number in range(self.starting_verse, self.ending_verse + 1)
        )


@dataclass(frozen=True, slots=True)
class TranslationSelector:
    """One offline-configurable way to select a translation resource."""

    kind: TranslationSelectorKind
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise ValueError("translation selector value cannot be blank")
        if self.kind == "id":
            try:
                resource_id = int(normalized)
            except ValueError as error:
                raise ValueError(
                    "translation resource ID must be a positive whole number"
                ) from error
            if resource_id < 1:
                raise ValueError(
                    "translation resource ID must be a positive whole number"
                )
            normalized = str(resource_id)
        elif self.kind not in {"slug", "language"}:
            raise ValueError(f"unsupported translation selector kind: {self.kind}")
        object.__setattr__(self, "value", normalized)

    @property
    def label(self) -> str:
        return f"{self.kind}={self.value}"


@dataclass(frozen=True, slots=True)
class LanguageResource:
    """A language advertised by the Quran Foundation resource catalog."""

    resource_id: int
    name: str
    native_name: str | None
    iso_code: str
    direction: str
    translations_count: int | None


@dataclass(frozen=True, slots=True)
class TranslationResource:
    """The exact translator/resource identity used for verse requests."""

    resource_id: str
    slug: str | None
    name: str
    author_name: str
    language_name: str
    language_code: str

    @property
    def display_name(self) -> str:
        if self.author_name.casefold() in self.name.casefold():
            return self.name
        return f"{self.name} — {self.author_name}"


@dataclass(frozen=True, slots=True)
class TranslationCatalog:
    """One immutable snapshot of the live language and translation catalogs."""

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
    chapter_number: int
    chapter_name: str
    verses: tuple[Verse, ...]


@dataclass(frozen=True, slots=True)
class GenerationResult:
    path: Path | None
    passage: Passage
