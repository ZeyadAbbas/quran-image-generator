"""Small immutable values shared by the generator's core services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
