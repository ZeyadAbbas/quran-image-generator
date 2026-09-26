from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from quran_image_generator.content import (
    QuranApiConfig,
    QuranApiPayloadError,
    QuranContentClient,
)
from quran_image_generator.models import (
    Chapter,
    GenerationRequest,
    InvalidVerseRangeError,
    random_generation_request,
)

BASE_URL = "https://apis-prelive.quran.foundation/content/api/v4"
CHAPTERS = (
    Chapter(1, "Al-Fatihah", 7),
    Chapter(2, "Al-Baqarah", 286),
    Chapter(114, "An-Nas", 6),
)


def _response(payload, *, status_code=200):
    return SimpleNamespace(
        status_code=status_code,
        headers={"Content-Type": "application/json"},
        json=lambda: payload,
    )


def _token_response():
    return _response(
        {
            "access_token": "fixture-token",
            "token_type": "bearer",
            "expires_in": 3600,
        }
    )


def _chapter_payload(chapters=CHAPTERS):
    return {
        "chapters": [
            {
                "id": chapter.number,
                "name_simple": chapter.name_simple,
                "verses_count": chapter.verses_count,
            }
            for chapter in chapters
        ]
    }


def _verse_record(
    chapter: int,
    number: int,
    resource_ids=(),
    *,
    include_content=True,
):
    record = {
        "id": (chapter * 1_000) + number,
        "chapter_id": chapter,
        "verse_number": number,
        "verse_key": f"{chapter}:{number}",
    }
    if include_content:
        record["words"] = [
            {"char_type_name": "word", "text_uthmani": f"word-{number}"}
        ]
        record["translations"] = [
            {"resource_id": int(resource_id), "text": f"translation-{resource_id}"}
            for resource_id in reversed(tuple(resource_ids))
        ]
    return record


def _page_payload(
    chapter: Chapter,
    page: int,
    resource_ids=(),
    *,
    requested_range=None,
):
    first = ((page - 1) * 50) + 1
    last = min(page * 50, chapter.verses_count)
    total_pages = (chapter.verses_count + 49) // 50
    verses = []
    for number in range(first, last + 1):
        include_content = requested_range is None or (
            requested_range[0] <= number <= requested_range[1]
        )
        verses.append(
            _verse_record(
                chapter.number,
                number,
                resource_ids,
                include_content=include_content,
            )
        )
    return {
        "verses": verses,
        "pagination": {
            "per_page": 50,
            "current_page": page,
            "next_page": page + 1 if page < total_pages else None,
            "total_pages": total_pages,
            "total_records": chapter.verses_count,
        },
    }


class RangeSession:
    def __init__(self, *, chapters=CHAPTERS, resource_ids=(), requested_range=None):
        self.chapters = tuple(chapters)
        self.resource_ids = tuple(resource_ids)
        self.requested_range = requested_range
        self.get_calls = []
        self.post_calls = []

    def post(self, uri, **kwargs):
        self.post_calls.append((uri, kwargs))
        return _token_response()

    def get(self, uri, **kwargs):
        self.get_calls.append((uri, kwargs))
        if uri.endswith("/chapters"):
            return _response(_chapter_payload(self.chapters))
        if "/verses/by_key/" in uri:
            chapter, number = (
                int(value) for value in uri.rsplit("/", maxsplit=1)[1].split(":")
            )
            return _response(
                {
                    "verse": _verse_record(
                        chapter,
                        number,
                        self.resource_ids,
                    )
                }
            )
        chapter_number = int(uri.rsplit("/", maxsplit=1)[1])
        chapter = next(
            item for item in self.chapters if item.number == chapter_number
        )
        page = kwargs["params"]["page"]
        return _response(
            _page_payload(
                chapter,
                page,
                self.resource_ids,
                requested_range=self.requested_range,
            )
        )


def _client(session, *, sleeper=lambda _delay: None):
    return QuranContentClient(
        QuranApiConfig("prelive", "fixture-client", "fixture-secret"),
        session=session,
        monotonic=lambda: 0.0,
        sleeper=sleeper,
        random_source=lambda: 0.0,
    )


@pytest.mark.parametrize(
    ("passage_request", "cold_count", "warm_count", "verse_paths", "pages"),
    (
        (GenerationRequest(1, 1, 1), 2, 1, ("verses/by_key/1:1",), ()),
        (GenerationRequest(1, 1, 7), 2, 1, ("verses/by_chapter/1",), (1,)),
        (
            GenerationRequest(2, 49, 52),
            3,
            2,
            ("verses/by_chapter/2", "verses/by_chapter/2"),
            (1, 2),
        ),
        (
            GenerationRequest(2, 1, 286),
            7,
            6,
            tuple("verses/by_chapter/2" for _ in range(6)),
            (1, 2, 3, 4, 5, 6),
        ),
        (GenerationRequest(114, 6, 6), 2, 1, ("verses/by_key/114:6",), ()),
    ),
)
def test_acceptance_ranges_use_minimal_endpoints_and_warm_catalog_cache(
    passage_request, cold_count, warm_count, verse_paths, pages
):
    session = RangeSession()
    client = _client(session)

    first = client.fetch_passage(passage_request, ())
    first_calls = tuple(session.get_calls)
    second = client.fetch_passage(passage_request, ())
    warm_calls = tuple(session.get_calls[len(first_calls) :])

    assert len(first_calls) == cold_count
    assert len(warm_calls) == warm_count
    assert [verse.number for verse in first.verses] == list(
        range(passage_request.starting_verse, passage_request.ending_verse + 1)
    )
    assert second == first
    assert first.chapter.number == passage_request.chapter
    assert first.chapter_name == first.chapter.name_simple
    assert first.chapter_number == first.chapter.number
    assert [call[0].removeprefix(f"{BASE_URL}/") for call in first_calls[1:]] == list(
        verse_paths
    )
    assert not any("chapters/" in call[0] for call in session.get_calls)
    if pages:
        assert [call[1]["params"]["page"] for call in first_calls[1:]] == list(
            pages
        )
        for _uri, kwargs in first_calls[1:]:
            assert kwargs["params"] == {
                "page": kwargs["params"]["page"],
                "per_page": 50,
                "words": 1,
                "word_fields": "text_uthmani",
            }


def test_verse_query_merges_pagination_but_keeps_content_fields_authoritative():
    session = RangeSession(resource_ids=(131, 31))
    client = _client(session)

    client.api_call(
        "verses/by_chapter/2",
        ("131", "31"),
        query={
            "page": 2,
            "per_page": 50,
            "words": 0,
            "word_fields": "wrong",
            "translations": "999",
        },
    )

    assert session.get_calls[0][1]["params"] == {
        "page": 2,
        "per_page": 50,
        "words": 1,
        "word_fields": "text_uthmani",
        "translations": "131,31",
    }


def test_partial_chapter_catalog_is_sorted_and_cached_across_clients():
    first_session = RangeSession(chapters=(CHAPTERS[2], CHAPTERS[0]))
    first = _client(first_session).list_chapters()
    second_session = RangeSession()

    second = _client(second_session).list_chapters()

    assert [chapter.number for chapter in first] == [1, 114]
    assert second is first
    assert len(first_session.get_calls) == 1
    assert second_session.get_calls == []
    assert second_session.post_calls == []


def test_chapter_catalog_refresh_replaces_snapshot_atomically():
    original = _client(RangeSession(chapters=(CHAPTERS[0],))).list_chapters()
    refresh_session = RangeSession(chapters=(CHAPTERS[1],))

    refreshed = _client(refresh_session).list_chapters(refresh=True)

    assert original == (CHAPTERS[0],)
    assert refreshed == (CHAPTERS[1],)
    assert _client(RangeSession()).list_chapters() is refreshed


def test_failed_chapter_refresh_preserves_previous_snapshot():
    original = _client(RangeSession(chapters=(CHAPTERS[0],))).list_chapters()

    with pytest.raises(QuranApiPayloadError, match="non-empty"):
        _client(RangeSession(chapters=())).list_chapters(refresh=True)

    untouched = RangeSession()
    assert _client(untouched).list_chapters() is original
    assert untouched.get_calls == []


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ({}, "chapters"),
        ({"chapters": []}, "non-empty"),
        ({"chapters": [None]}, "object"),
        ({"chapters": [{"id": True, "name_simple": "A", "verses_count": 1}]}, "id"),
        ({"chapters": [{"id": 115, "name_simple": "A", "verses_count": 1}]}, "id"),
        (
            {
                "chapters": [
                    {"id": 1, "name_simple": "A", "verses_count": 1},
                    {"id": 1, "name_simple": "B", "verses_count": 2},
                ]
            },
            "duplicated",
        ),
        ({"chapters": [{"id": 1, "name_simple": " ", "verses_count": 1}]}, "name_simple"),
        ({"chapters": [{"id": 1, "name_simple": "A", "verses_count": False}]}, "verses_count"),
    ),
)
def test_malformed_chapter_catalog_is_rejected(payload, message):
    class CatalogSession(RangeSession):
        def get(self, uri, **kwargs):
            self.get_calls.append((uri, kwargs))
            return _response(payload)

    with pytest.raises(QuranApiPayloadError, match=message):
        _client(CatalogSession()).list_chapters()


@pytest.mark.parametrize(
    "values",
    ((True, 1, 1), (1, False, 1), (1, 1, True), (0, 1, 1), (1, 0, 1), (1, 2, 1)),
)
def test_generation_request_rejects_invalid_values(values):
    with pytest.raises(InvalidVerseRangeError):
        GenerationRequest(*values)


@pytest.mark.parametrize(
    ("passage_request", "message"),
    (
        (GenerationRequest(2, 1, 1), "not available"),
        (GenerationRequest(1, 8, 8), "between 8 and 7"),
    ),
)
def test_invalid_live_range_fails_before_any_verse_request(passage_request, message):
    session = RangeSession(chapters=(CHAPTERS[0],))

    with pytest.raises(InvalidVerseRangeError, match=message):
        _client(session).fetch_passage(passage_request, ())

    assert [uri.removeprefix(f"{BASE_URL}/") for uri, _kwargs in session.get_calls] == [
        "chapters"
    ]


def _mutated_page(mutator):
    payload = _page_payload(CHAPTERS[0], 1)
    mutator(payload)
    return payload


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ({"verses": []}, "pagination"),
        ({"verses": "invalid", "pagination": {}}, "verses"),
        (_mutated_page(lambda item: item["verses"].pop()), "7 verse records"),
        (
            _mutated_page(
                lambda item: item["verses"].__setitem__(1, item["verses"][0])
            ),
            "duplicated",
        ),
        (
            _mutated_page(
                lambda item: item["verses"][0].__setitem__("verse_key", "2:1")
            ),
            "verse_key",
        ),
        (
            _mutated_page(
                lambda item: item["verses"][0].__setitem__("chapter_id", 2)
            ),
            "chapter_id",
        ),
        (
            _mutated_page(
                lambda item: item["verses"][0].__setitem__("chapter_id", True)
            ),
            "chapter_id",
        ),
        (
            _mutated_page(
                lambda item: item["verses"][0].__setitem__("chapter_id", 1.0)
            ),
            "chapter_id",
        ),
        (
            _mutated_page(
                lambda item: item["verses"][0].update(
                    {"verse_number": 8, "verse_key": "1:8"}
                )
            ),
            "natural window",
        ),
        (
            _mutated_page(
                lambda item: item["pagination"].__setitem__("total_records", 8)
            ),
            "total_records",
        ),
        (
            _mutated_page(
                lambda item: item["pagination"].__setitem__("total_pages", 2)
            ),
            "total_pages",
        ),
        (
            _mutated_page(
                lambda item: item["pagination"].__setitem__("current_page", 2)
            ),
            "current_page",
        ),
        (
            _mutated_page(
                lambda item: item["pagination"].__setitem__("per_page", 49)
            ),
            "per_page",
        ),
        (
            _mutated_page(
                lambda item: item["pagination"].__setitem__("next_page", 2)
            ),
            "next_page",
        ),
        (
            _mutated_page(lambda item: item["pagination"].pop("next_page")),
            "next_page",
        ),
    ),
)
def test_malformed_or_incomplete_page_is_rejected(payload, message):
    class PageSession(RangeSession):
        def get(self, uri, **kwargs):
            self.get_calls.append((uri, kwargs))
            if uri.endswith("/chapters"):
                return _response(_chapter_payload((CHAPTERS[0],)))
            return _response(deepcopy(payload))

    with pytest.raises(QuranApiPayloadError, match=message):
        _client(PageSession(chapters=(CHAPTERS[0],))).fetch_passage(
            GenerationRequest(1, 1, 2), ()
        )


def test_next_page_must_be_a_real_integer_not_an_equal_float():
    payload = _page_payload(CHAPTERS[1], 1)
    payload["pagination"]["next_page"] = 2.0

    class FloatPaginationSession(RangeSession):
        def get(self, uri, **kwargs):
            self.get_calls.append((uri, kwargs))
            if uri.endswith("/chapters"):
                return _response(_chapter_payload((CHAPTERS[1],)))
            return _response(deepcopy(payload))

    with pytest.raises(QuranApiPayloadError, match="next_page"):
        _client(FloatPaginationSession(chapters=(CHAPTERS[1],))).fetch_passage(
            GenerationRequest(2, 49, 52), ()
        )


def test_shuffled_page_is_reordered_and_neighbors_are_excluded():
    payload = _page_payload(CHAPTERS[0], 1)
    payload["verses"].reverse()
    for verse in payload["verses"]:
        verse["chapter_id"] = None

    class ShuffledSession(RangeSession):
        def get(self, uri, **kwargs):
            self.get_calls.append((uri, kwargs))
            if uri.endswith("/chapters"):
                return _response(_chapter_payload((CHAPTERS[0],)))
            return _response(deepcopy(payload))

    passage = _client(ShuffledSession(chapters=(CHAPTERS[0],))).fetch_passage(
        GenerationRequest(1, 2, 6), ()
    )

    assert [verse.number for verse in passage.verses] == [2, 3, 4, 5, 6]


def test_single_verse_accepts_explicit_null_chapter_id():
    class NullChapterSession(RangeSession):
        def get(self, uri, **kwargs):
            response = super().get(uri, **kwargs)
            if "/verses/by_key/" not in uri:
                return response
            payload = response.json()
            payload["verse"]["chapter_id"] = None
            return _response(payload)

    passage = _client(NullChapterSession(chapters=(CHAPTERS[0],))).fetch_passage(
        GenerationRequest(1, 1, 1), ()
    )

    assert passage.verses[0].key == "1:1"


@pytest.mark.parametrize("chapter_id", (2, True, 1.0))
def test_single_verse_rejects_malformed_non_null_chapter_id(chapter_id):
    class InvalidChapterSession(RangeSession):
        def get(self, uri, **kwargs):
            response = super().get(uri, **kwargs)
            if "/verses/by_key/" not in uri:
                return response
            payload = response.json()
            payload["verse"]["chapter_id"] = chapter_id
            return _response(payload)

    with pytest.raises(QuranApiPayloadError, match="chapter_id"):
        _client(InvalidChapterSession(chapters=(CHAPTERS[0],))).fetch_passage(
            GenerationRequest(1, 1, 1), ()
        )


def test_unused_page_neighbors_do_not_require_words_or_translations():
    session = RangeSession(
        chapters=(CHAPTERS[1],),
        resource_ids=(131, 31),
        requested_range=(49, 52),
    )

    passage = _client(session).fetch_passage(
        GenerationRequest(2, 49, 52), ("131", "31")
    )

    assert [verse.number for verse in passage.verses] == [49, 50, 51, 52]
    for verse in passage.verses:
        assert [item.resource_id for item in verse.translations] == ["131", "31"]
    for _uri, kwargs in session.get_calls[1:]:
        assert kwargs["params"]["translations"] == "131,31"


def test_missing_selected_translation_on_requested_page_record_is_rejected():
    payload = _page_payload(CHAPTERS[0], 1, (131,))
    payload["verses"][1]["translations"] = []

    class MissingTranslationSession(RangeSession):
        def get(self, uri, **kwargs):
            self.get_calls.append((uri, kwargs))
            if uri.endswith("/chapters"):
                return _response(_chapter_payload((CHAPTERS[0],)))
            return _response(deepcopy(payload))

    with pytest.raises(QuranApiPayloadError, match="resource 131"):
        _client(MissingTranslationSession(chapters=(CHAPTERS[0],))).fetch_passage(
            GenerationRequest(1, 1, 2), ("131",)
        )


def test_random_request_uses_available_catalog_and_injected_rng():
    calls = []

    class FixedRandom:
        def randrange(self, stop):
            calls.append(("randrange", stop))
            return 1

        def randint(self, start, stop):
            calls.append(("randint", start, stop))
            return 4 if len(calls) == 2 else 2

    request = random_generation_request((CHAPTERS[1], CHAPTERS[2]), FixedRandom())

    assert request == GenerationRequest(114, 4, 5)
    assert calls == [
        ("randrange", 2),
        ("randint", 1, 6),
        ("randint", 1, 3),
    ]


def test_random_request_never_runs_past_chapter_end():
    class LastVerseRandom:
        def randrange(self, stop):
            return 0

        def randint(self, start, stop):
            assert start == 1
            return stop

    assert random_generation_request((CHAPTERS[2],), LastVerseRandom()) == (
        GenerationRequest(114, 6, 6)
    )


def test_post_retry_single_identity_error_reports_real_attempt_count():
    class RetrySession(RangeSession):
        def __init__(self):
            super().__init__(chapters=(CHAPTERS[0],))
            self.verse_sends = 0

        def get(self, uri, **kwargs):
            self.get_calls.append((uri, kwargs))
            if uri.endswith("/chapters"):
                return _response(_chapter_payload((CHAPTERS[0],)))
            self.verse_sends += 1
            if self.verse_sends == 1:
                return _response(None, status_code=503)
            verse = _verse_record(1, 1)
            verse["verse_key"] = "1:2"
            return _response({"verse": verse})

    with pytest.raises(QuranApiPayloadError) as caught:
        _client(RetrySession()).fetch_passage(GenerationRequest(1, 1, 1), ())

    assert caught.value.attempts == 2


def test_post_retry_page_error_reports_real_attempt_count():
    class RetrySession(RangeSession):
        def __init__(self):
            super().__init__(chapters=(CHAPTERS[0],))
            self.page_sends = 0

        def get(self, uri, **kwargs):
            self.get_calls.append((uri, kwargs))
            if uri.endswith("/chapters"):
                return _response(_chapter_payload((CHAPTERS[0],)))
            self.page_sends += 1
            if self.page_sends == 1:
                return _response(None, status_code=503)
            payload = _page_payload(CHAPTERS[0], 1)
            payload["pagination"]["total_records"] = 8
            return _response(payload)

    with pytest.raises(QuranApiPayloadError) as caught:
        _client(RetrySession()).fetch_passage(GenerationRequest(1, 1, 2), ())

    assert caught.value.attempts == 2
