"""Authenticated Quran Foundation content access and response mapping."""

from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from .models import GenerationRequest, Passage, Verse, VerseTranslation

QURAN_FOUNDATION_ACCESS_URL = (
    "https://api-docs.quran.foundation/request-access/"
)
REQUEST_TIMEOUT_SECONDS = 30
TOKEN_EXPIRY_MARGIN_SECONDS = 30

_ENVIRONMENT_URLS = {
    "prelive": (
        "https://prelive-oauth2.quran.foundation",
        "https://apis-prelive.quran.foundation/content/api/v4",
    ),
    "production": (
        "https://oauth2.quran.foundation",
        "https://apis.quran.foundation/content/api/v4",
    ),
}


class QuranApiConfigurationError(ValueError):
    """Raised when Quran Foundation credentials are missing or invalid."""


class QuranApiError(RuntimeError):
    """Raised for a sanitized Quran Foundation API failure."""


def _canonical_environment(value: str) -> str:
    canonical = value.strip().lower() or "prelive"
    if canonical not in _ENVIRONMENT_URLS:
        raise QuranApiConfigurationError(
            "QF_ENV must be 'prelive' or 'production'."
        )
    return canonical


@dataclass(frozen=True, slots=True)
class QuranApiConfig:
    """Validated credentials with inseparable auth and content environments."""

    environment: str = field(repr=False)
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "environment", _canonical_environment(self.environment)
        )
        missing = tuple(
            name
            for name, value in (
                ("QF_CLIENT_ID", self.client_id),
                ("QF_CLIENT_SECRET", self.client_secret),
            )
            if not value.strip()
        )
        if missing:
            joined = ", ".join(missing)
            raise QuranApiConfigurationError(
                "Missing required Quran Foundation credentials: "
                f"{joined}. Create a backend app and set the environment "
                f"variables described at {QURAN_FOUNDATION_ACCESS_URL}"
            )

    @property
    def auth_base_url(self) -> str:
        return _ENVIRONMENT_URLS[self.environment][0]

    @property
    def content_base_url(self) -> str:
        return _ENVIRONMENT_URLS[self.environment][1]

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> QuranApiConfig:
        values = os.environ if environ is None else environ
        environment = values.get("QF_ENV", "prelive")
        missing = tuple(
            name
            for name in ("QF_CLIENT_ID", "QF_CLIENT_SECRET")
            if not values.get(name, "").strip()
        )
        if missing:
            joined = ", ".join(missing)
            raise QuranApiConfigurationError(
                "Missing required Quran Foundation credentials: "
                f"{joined}. Create a backend app and set the environment "
                f"variables described at {QURAN_FOUNDATION_ACCESS_URL}"
            )
        return cls(
            environment=environment,
            client_id=values["QF_CLIENT_ID"],
            client_secret=values["QF_CLIENT_SECRET"],
        )


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
    """Map one verse response to immutable domain data.

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
    """Fetch Quran content with a cached OAuth2 Client Credentials token."""

    def __init__(
        self,
        config: QuranApiConfig | None = None,
        *,
        session: Any | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._config = config or QuranApiConfig.from_environment()
        self._session = session or requests.Session()
        self._monotonic = monotonic
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be a positive finite number of seconds")
        self._timeout = float(timeout)
        self._token_lock = threading.Lock()
        self._access_token: str | None = None
        self._token_expires_at = 0.0

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        session: Any | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> QuranContentClient:
        """Build a client from QF_CLIENT_ID, QF_CLIENT_SECRET, and QF_ENV."""

        return cls(
            QuranApiConfig.from_environment(environ),
            session=session,
            monotonic=monotonic,
            timeout=timeout,
        )

    def _token_is_reusable(self, now: float) -> bool:
        return bool(self._access_token) and now < (
            self._token_expires_at - TOKEN_EXPIRY_MARGIN_SECONDS
        )

    def _request_token(self) -> str:
        response: Any | None = None
        try:
            response = self._session.post(
                f"{self._config.auth_base_url}/oauth2/token",
                auth=HTTPBasicAuth(
                    self._config.client_id,
                    self._config.client_secret,
                ),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "client_credentials",
                    "scope": "content",
                },
                timeout=self._timeout,
            )
        except (requests.RequestException, UnicodeError):
            # Do not retain an exception that may carry prepared Basic auth.
            response = None

        if response is None:
            raise QuranApiError(
                "Could not reach the Quran Foundation token endpoint."
            )

        status_code = getattr(response, "status_code", None)
        if not isinstance(status_code, int):
            raise QuranApiError("The token endpoint returned an invalid response.")
        if not 200 <= status_code < 300:
            raise QuranApiError(
                f"Quran Foundation token request failed with HTTP {status_code}."
            )

        payload: Any | None = None
        invalid_json = False
        try:
            payload = response.json()
        except (TypeError, ValueError):
            invalid_json = True
        if invalid_json:
            raise QuranApiError("The token endpoint returned invalid JSON.")
        if not isinstance(payload, Mapping):
            raise QuranApiError("The token endpoint returned an invalid payload.")

        access_token = payload.get("access_token")
        token_type = payload.get("token_type")
        expires_in = payload.get("expires_in")
        if not isinstance(access_token, str) or not access_token.strip():
            raise QuranApiError(
                "The token endpoint response is missing a valid access_token."
            )
        if token_type is not None and (
            not isinstance(token_type, str) or token_type.lower() != "bearer"
        ):
            raise QuranApiError(
                "The token endpoint returned an unsupported token_type."
            )
        if (
            isinstance(expires_in, bool)
            or not isinstance(expires_in, (int, float))
            or not math.isfinite(expires_in)
            or expires_in <= 0
        ):
            raise QuranApiError(
                "The token endpoint response is missing a valid expires_in."
            )

        self._access_token = access_token
        self._token_expires_at = self._monotonic() + float(expires_in)
        return access_token

    def _get_access_token(self) -> str:
        if self._token_is_reusable(self._monotonic()):
            return self._access_token or ""
        with self._token_lock:
            if self._token_is_reusable(self._monotonic()):
                return self._access_token or ""
            return self._request_token()

    def _invalidate_access_token(self, rejected_token: str) -> None:
        with self._token_lock:
            if self._access_token == rejected_token:
                self._access_token = None
                self._token_expires_at = 0.0

    def _content_request(
        self, endpoint: str, params: Mapping[str, Any] | None
    ) -> Any:
        token = self._get_access_token()
        response = self._send_content_request(endpoint, params, token)
        if getattr(response, "status_code", None) == 401:
            self._invalidate_access_token(token)
            token = self._get_access_token()
            response = self._send_content_request(endpoint, params, token)
        return response

    def _send_content_request(
        self,
        endpoint: str,
        params: Mapping[str, Any] | None,
        token: str,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "headers": {
                "Accept": "application/json",
                "x-auth-token": token,
                "x-client-id": self._config.client_id,
            },
            "timeout": self._timeout,
        }
        if params is not None:
            kwargs["params"] = params

        response: Any | None = None
        try:
            response = self._session.get(
                f"{self._config.content_base_url}/{endpoint.lstrip('/')}",
                **kwargs,
            )
        except (requests.RequestException, UnicodeError):
            # Do not retain an exception that may carry authenticated headers.
            response = None

        if response is None:
            raise QuranApiError(
                "Could not reach the Quran Foundation Content API."
            )
        return response

    def api_call(
        self, endpoint: str, translation_resource_ids: Sequence[str] = ()
    ) -> Mapping[str, Any]:
        """Call one supported Content API endpoint and return its JSON object."""

        params: Mapping[str, Any] | None = None
        if endpoint.lstrip("/").startswith("verses/"):
            params = {
                "words": True,
                "word_fields": "text_uthmani",
            }
            if translation_resource_ids:
                params = {
                    **params,
                    "translations": ",".join(translation_resource_ids),
                }

        response = self._content_request(endpoint, params)
        status_code = getattr(response, "status_code", None)
        if not isinstance(status_code, int):
            raise QuranApiError("The Content API returned an invalid response.")
        if not 200 <= status_code < 300:
            raise QuranApiError(
                f"Quran Foundation Content API request failed with HTTP "
                f"{status_code}."
            )
        payload: Any | None = None
        invalid_json = False
        try:
            payload = response.json()
        except (TypeError, ValueError):
            invalid_json = True
        if invalid_json:
            raise QuranApiError("The Content API returned invalid JSON.")
        if not isinstance(payload, Mapping):
            raise QuranApiError("The Content API returned an invalid payload.")
        return payload

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
