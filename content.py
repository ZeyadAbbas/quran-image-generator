"""Legacy Quran.com content access and response mapping.

The request contract intentionally remains unchanged here. Authentication,
batching, retries, and the new API contract belong to the later API pass.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import requests

from models import GenerationRequest, Passage, Verse, VerseTranslation

QURAN_API_BASE_URL = "https://api.quran.com/api/v4"


def parse_verse(
    payload: Mapping[str, Any], requested_resource_ids: Sequence[str]
) -> Verse:
    """Map one legacy verse response to immutable domain data.

    The old implementation always discarded the final word item. That behavior
    is retained until the text-normalization work in #9 can use token metadata.
    """

    verse_data = payload["verse"]
    raw_words = verse_data["words"]
    words = tuple(str(word["text"]) for word in raw_words[:-1])

    translations_by_id = {
        str(item["resource_id"]): VerseTranslation(
            resource_id=str(item["resource_id"]),
            text=str(item["text"]),
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
