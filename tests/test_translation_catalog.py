from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from quran_image_generator.content import (
    QuranApiConfig,
    QuranApiPayloadError,
    QuranContentClient,
    TranslationSelectionError,
)
from quran_image_generator.models import TranslationSelector

TRANSLATIONS_PAYLOAD = {
    "translations": [
        {
            "id": 131,
            "name": "The Clear Quran",
            "author_name": "Dr. Mustafa Khattab",
            "slug": "clearquran-with-tafsir",
            "language_name": "English",
            "translated_name": {
                "name": "The Clear Quran",
                "language_name": "English",
            },
        },
        {
            "id": 85,
            "name": "Saheeh International",
            "author_name": "Saheeh International",
            "slug": "saheeh-international",
            "language_name": "English",
            "translated_name": {
                "name": "Saheeh International",
                "language_name": "English",
            },
        },
        {
            "id": 31,
            "name": "French Translation",
            "author_name": "Muhammad Hamidullah",
            "slug": "muhammad-hamidullah",
            "language_name": "French",
            "translated_name": {
                "name": "French Translation",
                "language_name": "English",
            },
        },
        {
            "id": 83,
            "name": "Spanish Translation",
            "author_name": "Sheikh Isa Garcia",
            "slug": "sheikh-isa-garcia",
            "language_name": "Spanish",
            "translated_name": {
                "name": "Spanish Translation",
                "language_name": "English",
            },
        },
    ]
}

LANGUAGES_PAYLOAD = {
    "languages": [
        {
            "id": 1,
            "name": "English",
            "native_name": "English",
            "iso_code": "en",
            "direction": "ltr",
            "translations_count": 2,
            "translated_name": {"name": "English", "language_name": "English"},
        },
        {
            "id": 2,
            "name": "French",
            "native_name": "Français",
            "iso_code": "fr",
            "direction": "ltr",
            "translations_count": 1,
            "translated_name": {"name": "French", "language_name": "English"},
        },
        {
            "id": 3,
            "name": "Spanish",
            "native_name": "Español",
            "iso_code": "es",
            "direction": "ltr",
            "translations_count": 1,
            "translated_name": {"name": "Spanish", "language_name": "English"},
        },
    ]
}


def _response(payload, status_code=200, content_type="application/json"):
    return SimpleNamespace(
        status_code=status_code,
        headers={"Content-Type": content_type},
        json=lambda: deepcopy(payload),
    )


class CatalogSession:
    def __init__(self, translations=None, languages=None):
        self.translations = translations or TRANSLATIONS_PAYLOAD
        self.languages = languages or LANGUAGES_PAYLOAD
        self.get_calls = []
        self.post_calls = []

    def post(self, uri, **kwargs):
        self.post_calls.append((uri, kwargs))
        return _response(
            {
                "access_token": "catalog-token",
                "token_type": "bearer",
                "expires_in": 3600,
            }
        )

    def get(self, uri, **kwargs):
        self.get_calls.append((uri, kwargs))
        payload = (
            self.languages if uri.endswith("resources/languages") else self.translations
        )
        return payload if hasattr(payload, "status_code") else _response(payload)


def _client(session):
    return QuranContentClient(
        QuranApiConfig("prelive", "catalog-client", "catalog-secret"),
        session=session,
        monotonic=lambda: 0.0,
    )


@pytest.fixture(autouse=True)
def isolated_catalog_cache():
    QuranContentClient.clear_translation_catalog_cache()
    yield
    QuranContentClient.clear_translation_catalog_cache()


def test_catalog_fetches_both_localized_resources_and_models_exact_identity():
    session = CatalogSession()

    catalog = _client(session).translation_catalog()

    assert [resource.resource_id for resource in catalog.resources] == [
        "131",
        "85",
        "31",
        "83",
    ]
    clear_quran = catalog.resources[0]
    assert clear_quran.slug == "clearquran-with-tafsir"
    assert clear_quran.author_name == "Dr. Mustafa Khattab"
    assert clear_quran.language_code == "en"
    assert [call[0].rsplit("/", 2)[-2:] for call in session.get_calls] == [
        ["resources", "translations"],
        ["resources", "languages"],
    ]
    assert [call[1]["params"] for call in session.get_calls] == [
        {"language": "en"},
        {"language": "en"},
    ]
    with pytest.raises(FrozenInstanceError):
        clear_quran.name = "changed"  # type: ignore[misc]


def test_exact_id_slug_and_three_resource_order_are_preserved():
    client = _client(CatalogSession())

    resources = client.resolve_translations(
        (
            TranslationSelector("slug", "sheikh-isa-garcia"),
            TranslationSelector("id", "131"),
            TranslationSelector("slug", "muhammad-hamidullah"),
        )
    )

    assert [resource.resource_id for resource in resources] == ["83", "131", "31"]
    assert resources[1].display_name == "The Clear Quran — Dr. Mustafa Khattab"


def test_language_shortcut_only_succeeds_when_unambiguous():
    client = _client(CatalogSession())

    assert (
        client.resolve_translations((TranslationSelector("language", "fr"),))[
            0
        ].resource_id
        == "31"
    )
    with pytest.raises(TranslationSelectionError) as caught:
        client.resolve_translations((TranslationSelector("language", "en"),))

    message = str(caught.value)
    assert "ambiguous" in message
    assert "id=131" in message
    assert "clearquran-with-tafsir" in message
    assert "id=85" in message
    assert "Saheeh International" in message


@pytest.mark.parametrize(
    "selector",
    (TranslationSelector("id", "9999"), TranslationSelector("slug", "retired")),
)
def test_unknown_exact_selection_has_actionable_current_alternatives(selector):
    with pytest.raises(TranslationSelectionError) as caught:
        _client(CatalogSession()).resolve_translations((selector,))

    message = str(caught.value)
    assert selector.label in message
    assert "id=131" in message
    assert "--list-translations" in message


def test_two_selectors_cannot_resolve_to_the_same_resource():
    with pytest.raises(TranslationSelectionError, match="already selected"):
        _client(CatalogSession()).resolve_translations(
            (
                TranslationSelector("id", "131"),
                TranslationSelector("slug", "clearquran-with-tafsir"),
            )
        )


def test_catalog_is_cached_across_clients_until_explicit_refresh():
    first_session = CatalogSession()
    first = _client(first_session).translation_catalog()
    second_session = CatalogSession()
    second_client = _client(second_session)

    assert second_client.translation_catalog() is first
    assert second_session.get_calls == []

    refreshed_payload = deepcopy(TRANSLATIONS_PAYLOAD)
    refreshed_payload["translations"][0]["name"] = "Refreshed Clear Quran"
    second_session.translations = refreshed_payload
    refreshed = second_client.translation_catalog(refresh=True)

    assert refreshed is not first
    assert refreshed.resources[0].name == "Refreshed Clear Quran"
    assert len(second_session.get_calls) == 2
    assert _client(CatalogSession()).translation_catalog() is refreshed


def test_failed_refresh_preserves_the_previous_atomic_snapshot():
    original = _client(CatalogSession()).translation_catalog()
    bad_languages = _response({"languages": "invalid"})

    with pytest.raises(QuranApiPayloadError, match="languages must be a list"):
        _client(CatalogSession(languages=bad_languages)).translation_catalog(
            refresh=True
        )

    untouched_session = CatalogSession()
    assert _client(untouched_session).translation_catalog() is original
    assert untouched_session.get_calls == []


def test_duplicate_catalog_identity_is_rejected_by_payload_validation():
    duplicate = deepcopy(TRANSLATIONS_PAYLOAD)
    duplicate["translations"][1]["slug"] = "clearquran-with-tafsir"

    with pytest.raises(QuranApiPayloadError, match="slug.*duplicated"):
        _client(CatalogSession(translations=duplicate)).translation_catalog()


def test_catalog_accepts_documented_optional_display_metadata():
    translations = deepcopy(TRANSLATIONS_PAYLOAD)
    languages = deepcopy(LANGUAGES_PAYLOAD)
    for resource in translations["translations"]:
        resource.pop("translated_name")
    for language in languages["languages"]:
        language.pop("translations_count")
        language.pop("translated_name")

    catalog = _client(CatalogSession(translations, languages)).translation_catalog()

    assert catalog.resources[0].resource_id == "131"
    assert catalog.languages[0].translations_count is None


def test_blank_optional_aliases_do_not_poison_mixed_catalog_or_ids():
    translations = deepcopy(TRANSLATIONS_PAYLOAD)
    translations["translations"].extend(
        [
            {
                "id": 136,
                "name": "Uzbek Translation",
                "author_name": "Muhammad Sodik Muhammad Yusuf",
                "slug": None,
                "language_name": "Uzbek",
            },
            {
                "id": 135,
                "name": "Tajik Translation",
                "author_name": "AbdolMohammad Ayati",
                "slug": "",
                "language_name": "Tajik",
            },
        ]
    )
    languages = deepcopy(LANGUAGES_PAYLOAD)
    languages["languages"].extend(
        [
            {
                "id": 4,
                "name": "Uzbek",
                "native_name": "",
                "iso_code": "uz",
                "direction": "ltr",
                "translations_count": 1,
            },
            {
                "id": 5,
                "name": "Tajik",
                "native_name": None,
                "iso_code": "tj",
                "direction": "ltr",
                "translations_count": 1,
            },
        ]
    )
    client = _client(CatalogSession(translations, languages))

    resolved = client.resolve_translations(
        (
            TranslationSelector("id", "131"),
            TranslationSelector("id", "136"),
            TranslationSelector("id", "135"),
        )
    )

    assert [resource.resource_id for resource in resolved] == ["131", "136", "135"]
    assert [resource.slug for resource in resolved[1:]] == [None, None]
    assert [language.native_name for language in client.translation_catalog().languages[-2:]] == [
        None,
        None,
    ]
    assert client.resolve_translations(
        (TranslationSelector("language", "uz"),)
    )[0].resource_id == "136"


def test_duplicate_iso_rows_are_one_logical_language_for_shortcuts():
    translations = {
        "translations": [
            {
                "id": 59,
                "name": "Albanian Translation",
                "author_name": "Sherif Ahmeti",
                "slug": "sherif-ahmeti",
                "language_name": "Albanian",
            }
        ]
    }
    languages = {
        "languages": [
            {
                "id": 187,
                "name": "Albanian",
                "native_name": "Shqip",
                "iso_code": "sq",
                "direction": "ltr",
            },
            {
                "id": 151,
                "name": "Albanian",
                "native_name": "",
                "iso_code": "sq",
                "direction": "ltr",
            },
        ]
    }
    client = _client(CatalogSession(translations, languages))

    by_code = client.resolve_translations((TranslationSelector("language", "sq"),))
    by_name = client.resolve_translations(
        (TranslationSelector("language", "Albanian"),)
    )

    assert by_code[0].resource_id == "59"
    assert by_name[0].resource_id == "59"
    assert by_code[0].language_code == "sq"


def test_comma_separated_language_aliases_prevent_false_unique_shortcut():
    translations = {
        "translations": [
            {
                "id": 86,
                "name": "Divehi Translation",
                "author_name": "Office of the President of Maldives",
                "slug": "divehi-translation",
                "language_name": "Divehi, Dhivehi, Maldivian",
            },
            {
                "id": 840,
                "name": "Divehi Translation (New)",
                "author_name": "Maldives Translation Team",
                "slug": None,
                "language_name": "divehi",
            },
        ]
    }
    languages = {
        "languages": [
            {
                "id": 6,
                "name": "Divehi, Dhivehi, Maldivian",
                "native_name": "",
                "iso_code": "dv",
                "direction": "rtl",
            }
        ]
    }
    client = _client(CatalogSession(translations, languages))

    catalog = client.translation_catalog()
    assert [resource.language_code for resource in catalog.resources] == ["dv", "dv"]
    with pytest.raises(TranslationSelectionError) as caught:
        client.resolve_translations((TranslationSelector("language", "dv"),))

    message = str(caught.value)
    assert "ambiguous" in message
    assert "id=86" in message
    assert "id=840" in message
    assert "slug=None" not in message
