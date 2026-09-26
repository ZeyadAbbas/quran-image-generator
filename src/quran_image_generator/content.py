"""Legacy Quran.com content access and response mapping.

The request contract intentionally remains unchanged here. Authentication,
batching, retries, and the new API contract belong to the later API pass.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from html.parser import HTMLParser
from typing import Any

import requests

from .models import GenerationRequest, Passage, Verse, VerseTranslation

QURAN_API_BASE_URL = "https://api.quran.com/api/v4"


class _TranslationHTMLParser(HTMLParser):
    """Turn the small HTML subset returned by Quran.com into readable text."""

    _BLOCK_TAGS = frozenset({"br", "div", "li", "p"})
    _IGNORED_TAGS = frozenset({"script", "style"})
    _FOOTNOTE_ATTRIBUTES = frozenset(
        {"foot_note", "footnote", "data-footnote", "data-foot_note"}
    )
    _VOID_TAGS = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._open_tags: list[tuple[str, bool]] = []
        self._suppressed_count = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in self._VOID_TAGS:
            if not self._suppressed_count and normalized_tag in self._BLOCK_TAGS:
                self.parts.append(" ")
            return

        attribute_names = {name.lower() for name, _ in attrs}
        suppresses_content = normalized_tag in self._IGNORED_TAGS or (
            normalized_tag == "sup"
            and bool(attribute_names & self._FOOTNOTE_ATTRIBUTES)
        )
        if not self._suppressed_count and normalized_tag in self._BLOCK_TAGS:
            self.parts.append(" ")
        self._open_tags.append((normalized_tag, suppresses_content))
        if suppresses_content:
            self._suppressed_count += 1

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in self._VOID_TAGS:
            return

        matching_index = next(
            (
                index
                for index in range(len(self._open_tags) - 1, -1, -1)
                if self._open_tags[index][0] == normalized_tag
            ),
            None,
        )
        if matching_index is None:
            return

        _, suppresses_content = self._open_tags.pop(matching_index)
        if suppresses_content:
            self._suppressed_count -= 1
        if not self._suppressed_count and normalized_tag in self._BLOCK_TAGS:
            self.parts.append(" ")

    def handle_startendtag(
        self, tag: str, _attrs: list[tuple[str, str | None]]
    ) -> None:
        if not self._suppressed_count and tag.lower() in self._BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._suppressed_count:
            self.parts.append(data)


def _normalize_translation_text(text: str) -> str:
    parser = _TranslationHTMLParser()
    parser.feed(text)
    parser.close()
    without_delimiters = "".join(parser.parts).translate(
        str.maketrans("", "", "˹˺")
    )
    return " ".join(without_delimiters.replace("\xa0", " ").split())


def _word_text(word: Mapping[str, Any]) -> str:
    uthmani = word.get("text_uthmani")
    if uthmani is None or (isinstance(uthmani, str) and not uthmani.strip()):
        uthmani = word["text"]
    return str(uthmani)


def parse_verse(
    payload: Mapping[str, Any], requested_resource_ids: Sequence[str]
) -> Verse:
    """Map one legacy verse response to immutable domain data.

    Word and translation values are copied into immutable models.  Only tokens
    explicitly identified as verse-end markers are omitted.
    """

    verse_data = payload["verse"]
    raw_words = verse_data["words"]
    words = tuple(
        _word_text(word)
        for word in raw_words
        if str(word.get("char_type_name", "")).lower() != "end"
    )

    translations_by_id = {
        str(item["resource_id"]): VerseTranslation(
            resource_id=str(item["resource_id"]),
            text=_normalize_translation_text(str(item["text"])),
        )
        for item in verse_data.get("translations", ())
    }
    translations = tuple(
        translations_by_id[resource_id] for resource_id in requested_resource_ids
    )

    return Verse(
        number=int(verse_data["verse_number"]),
        key=str(verse_data.get("verse_key", "")),
        words=words,
        translations=translations,
    )


class QuranContentClient:
    """Fetch Quran content through the repository's existing HTTP contract."""

    def __init__(
        self,
        http_get: Callable[..., Any] | None = None,
        base_url: str = QURAN_API_BASE_URL,
    ) -> None:
        self._http_get = http_get or requests.get
        self._base_url = base_url.rstrip("/")

    def api_call(
        self, endpoint: str, translation_resource_ids: Sequence[str]
    ) -> Mapping[str, Any]:
        params = {
            "translations": ", ".join(translation_resource_ids),
            "words": 1,
            "word_fields": "text_uthmani",
        }
        response = self._http_get(
            f"{self._base_url}/{endpoint}",
            headers={"Accept": "application/json"},
            data={},
            params=params,
        )
        return response.json()

    def fetch_passage(
        self,
        request: GenerationRequest,
        translation_resource_ids: Sequence[str],
    ) -> Passage:
        resource_ids = tuple(translation_resource_ids)
        verses = tuple(
            parse_verse(
                self.api_call(f"verses/by_key/{key}", resource_ids),
                resource_ids,
            )
            for key in request.verse_keys()
        )
        if not verses:
            return Passage(request.chapter, "", ())

        chapter_payload = self.api_call(f"chapters/{request.chapter}", resource_ids)
        chapter_name = str(chapter_payload["chapter"]["name_simple"])
        return Passage(request.chapter, chapter_name, verses)
