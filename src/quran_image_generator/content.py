"""Authenticated Quran Foundation content access and response mapping."""

from __future__ import annotations

import math
import os
import random
import re
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
# Kept for callers that imported the original scalar timeout constant.
REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_REQUEST_TIMEOUT = (5.0, 30.0)
TOKEN_EXPIRY_MARGIN_SECONDS = 30
MAX_TRANSIENT_RETRIES = 2
MAX_CONTENT_SENDS = 4
MAX_RETRY_WAIT_SECONDS = 30.0
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

_INITIAL_BACKOFF_SECONDS = 0.5
_RETRY_AFTER_DELTA_PATTERN = re.compile(r"^[0-9]+$")
_INVALID_JSON = object()

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
    """Base class for sanitized Quran Foundation API failures."""


class QuranApiTransportError(QuranApiError):
    """A network failure that never retains the original request exception."""

    def __init__(self, operation: str, endpoint: str, attempts: int) -> None:
        self.operation = operation
        self.endpoint = endpoint
        self.attempts = attempts
        super().__init__(
            f"{operation} request to {endpoint} could not reach Quran Foundation "
            f"after {attempts} attempt(s). Check the network and try again."
        )


class QuranApiHttpError(QuranApiError):
    """A non-success HTTP response containing safe metadata only."""

    def __init__(
        self,
        operation: str,
        endpoint: str,
        status_code: int,
        attempts: int,
        *,
        guidance: str | None = None,
    ) -> None:
        self.operation = operation
        self.endpoint = endpoint
        self.status_code = status_code
        self.attempts = attempts
        suffix = f" {guidance}" if guidance else ""
        super().__init__(
            f"{operation} request to {endpoint} failed with HTTP {status_code} "
            f"after {attempts} attempt(s).{suffix}"
        )


# Conventional acronym spelling retained as an import-friendly alias.
QuranApiHTTPError = QuranApiHttpError


class QuranApiPayloadError(QuranApiError):
    """A successful response with invalid metadata, JSON, or required fields."""

    def __init__(
        self,
        operation: str,
        endpoint: str,
        attempts: int,
        problem: str,
    ) -> None:
        self.operation = operation
        self.endpoint = endpoint
        self.attempts = attempts
        self.problem = problem
        super().__init__(
            f"{operation} response from {endpoint} was invalid after "
            f"{attempts} attempt(s): {problem}."
        )


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


def _validate_timeout(
    timeout: float | tuple[float, float],
) -> tuple[float, float]:
    values: tuple[Any, Any]
    if isinstance(timeout, (bool, int, float)):
        values = (timeout, timeout)
    elif isinstance(timeout, (tuple, list)) and len(timeout) == 2:
        values = (timeout[0], timeout[1])
    else:
        raise ValueError(
            "timeout must contain positive finite connect and read seconds"
        )

    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
        for value in values
    ):
        raise ValueError(
            "timeout must contain positive finite connect and read seconds"
        )
    return (float(values[0]), float(values[1]))


def _safe_endpoint(endpoint: str) -> str:
    """Keep error context useful without echoing query strings or fragments."""

    path = endpoint.split("?", maxsplit=1)[0].split("#", maxsplit=1)[0]
    normalized = path.strip().lstrip("/")
    return f"/{normalized}" if normalized else "/"


def _response_header(response: Any, name: str) -> str | None:
    """Read one header without retaining unsafe response metadata or failures."""

    headers: Any | None = None
    try:
        headers = getattr(response, "headers", None)
    except Exception:  # noqa: BLE001 - third-party response metadata is untrusted
        headers = None
    if not isinstance(headers, Mapping):
        return None

    value: Any | None = None
    try:
        value = headers.get(name)
        if value is None:
            lowered = name.lower()
            value = next(
                (
                    item
                    for key, item in headers.items()
                    if isinstance(key, str) and key.lower() == lowered
                ),
                None,
            )
    except Exception:  # noqa: BLE001 - never retain unsafe header exceptions
        value = None
    return value if isinstance(value, str) else None


def _has_json_content_type(response: Any) -> bool:
    value = _response_header(response, "Content-Type")
    if value is None:
        return False
    media_type = value.split(";", maxsplit=1)[0].strip().lower()
    if media_type == "application/json":
        return True
    if not media_type.startswith("application/"):
        return False
    subtype = media_type.removeprefix("application/")
    return bool(subtype.removesuffix("+json")) and subtype.endswith("+json")


def _is_non_string_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _verse_payload_problem(
    payload: Mapping[str, Any], requested_resource_ids: Sequence[str]
) -> str | None:
    verse = payload.get("verse")
    if not isinstance(verse, Mapping):
        return "missing a verse object"

    verse_number = verse.get("verse_number")
    if (
        isinstance(verse_number, bool)
        or not isinstance(verse_number, int)
        or verse_number < 1
    ):
        return "verse_number must be a positive integer"
    verse_key = verse.get("verse_key")
    if not isinstance(verse_key, str) or not verse_key.strip():
        return "verse_key must be a non-empty string"

    words = verse.get("words")
    if not _is_non_string_sequence(words):
        return "words must be a list"
    for word in words:
        if not isinstance(word, Mapping):
            return "each word must be an object"
        char_type = word.get("char_type_name")
        if not isinstance(char_type, str) or not char_type.strip():
            return "word char_type_name must be a non-empty string"
        if char_type.lower() == "end":
            continue
        uthmani = word.get("text_uthmani")
        legacy = word.get("text")
        if uthmani is not None and not isinstance(uthmani, str):
            return "word text_uthmani must be a string"
        if legacy is not None and not isinstance(legacy, str):
            return "word text must be a string"
        if not (
            isinstance(uthmani, str)
            and uthmani.strip()
            or isinstance(legacy, str)
            and legacy.strip()
        ):
            return "each Quran word must include text"

    translations = verse.get("translations", ())
    if not _is_non_string_sequence(translations):
        return "translations must be a list"
    available_resource_ids: set[str] = set()
    for translation in translations:
        if not isinstance(translation, Mapping):
            return "each translation must be an object"
        resource_id = translation.get("resource_id")
        if isinstance(resource_id, bool) or not isinstance(
            resource_id, (int, str)
        ):
            return "translation resource_id is invalid"
        if isinstance(resource_id, str) and not resource_id.strip():
            return "translation resource_id is invalid"
        if not isinstance(translation.get("text"), str):
            return "translation text must be a string"
        available_resource_ids.add(str(resource_id))

    if any(
        resource_id not in available_resource_ids
        for resource_id in requested_resource_ids
    ):
        return "missing a requested translation"
    return None


def _chapter_payload_problem(payload: Mapping[str, Any]) -> str | None:
    chapter = payload.get("chapter")
    if not isinstance(chapter, Mapping):
        return "missing a chapter object"
    name = chapter.get("name_simple")
    if not isinstance(name, str) or not name.strip():
        return "chapter name_simple must be a non-empty string"
    return None


class QuranContentClient:
    """Fetch Quran content with bounded retries and a cached OAuth2 token.

    Token acquisition has at most three attempts.  A Content API operation has
    at most two transient retries plus one independent 401 refresh/replay, and
    never sends more than four authenticated requests in total.
    """

    def __init__(
        self,
        config: QuranApiConfig | None = None,
        *,
        session: Any | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        timeout: float | tuple[float, float] = DEFAULT_REQUEST_TIMEOUT,
        sleeper: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self._config = config or QuranApiConfig.from_environment()
        self._session = session if session is not None else requests.Session()
        self._monotonic = monotonic
        self._timeout = _validate_timeout(timeout)
        self._sleeper = sleeper
        self._random_source = random_source
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
        timeout: float | tuple[float, float] = DEFAULT_REQUEST_TIMEOUT,
        sleeper: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> QuranContentClient:
        """Build a client from QF_CLIENT_ID, QF_CLIENT_SECRET, and QF_ENV."""

        return cls(
            QuranApiConfig.from_environment(environ),
            session=session,
            monotonic=monotonic,
            timeout=timeout,
            sleeper=sleeper,
            random_source=random_source,
        )

    def _token_is_reusable(self, now: float) -> bool:
        return bool(self._access_token) and now < (
            self._token_expires_at - TOKEN_EXPIRY_MARGIN_SECONDS
        )

    def _request_token(self) -> str:
        operation = "Quran Foundation token"
        endpoint = "/oauth2/token"
        transient_retries = 0
        attempts = 0
        response: Any | None = None

        while True:
            attempts += 1
            response = None
            try:
                response = self._session.post(
                    f"{self._config.auth_base_url}/oauth2/token",
                    auth=HTTPBasicAuth(
                        self._config.client_id,
                        self._config.client_secret,
                    ),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    data={
                        "grant_type": "client_credentials",
                        "scope": "content",
                    },
                    timeout=self._timeout,
                )
            except (requests.RequestException, UnicodeError):
                # Never retain exceptions that may contain prepared Basic auth.
                response = None

            if response is None:
                if transient_retries >= MAX_TRANSIENT_RETRIES:
                    raise QuranApiTransportError(
                        operation, endpoint, attempts
                    ) from None
                self._sleep_for_retry(transient_retries, None)
                transient_retries += 1
                continue

            status_code = self._status_code(
                response, operation, endpoint, attempts
            )
            if status_code in RETRYABLE_STATUS_CODES:
                if transient_retries >= MAX_TRANSIENT_RETRIES:
                    raise self._http_error(
                        operation, endpoint, status_code, attempts
                    )
                if not self._sleep_for_retry(transient_retries, response):
                    raise self._http_error(
                        operation,
                        endpoint,
                        status_code,
                        attempts,
                        retry_after_too_large=True,
                    )
                transient_retries += 1
                continue
            if not 200 <= status_code < 300:
                raise self._http_error(
                    operation, endpoint, status_code, attempts
                )
            break

        payload = self._json_payload(response, operation, endpoint, attempts)

        access_token = payload.get("access_token")
        token_type = payload.get("token_type")
        expires_in = payload.get("expires_in")
        if not isinstance(access_token, str) or not access_token.strip():
            raise QuranApiPayloadError(
                operation,
                endpoint,
                attempts,
                "missing a valid access_token",
            )
        if token_type is not None and (
            not isinstance(token_type, str) or token_type.lower() != "bearer"
        ):
            raise QuranApiPayloadError(
                operation,
                endpoint,
                attempts,
                "unsupported token_type",
            )
        if (
            isinstance(expires_in, bool)
            or not isinstance(expires_in, (int, float))
            or not math.isfinite(expires_in)
            or expires_in <= 0
        ):
            raise QuranApiPayloadError(
                operation,
                endpoint,
                attempts,
                "missing a valid expires_in",
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
    ) -> tuple[Any, int]:
        operation = "Quran Foundation Content API"
        safe_endpoint = _safe_endpoint(endpoint)
        token = self._get_access_token()
        transient_retries = 0
        auth_replayed = False
        sends = 0

        while sends < MAX_CONTENT_SENDS:
            sends += 1
            response = self._send_content_request(endpoint, params, token)
            if response is None:
                if (
                    transient_retries >= MAX_TRANSIENT_RETRIES
                    or sends >= MAX_CONTENT_SENDS
                ):
                    raise QuranApiTransportError(
                        operation, safe_endpoint, sends
                    ) from None
                self._sleep_for_retry(transient_retries, None)
                transient_retries += 1
                continue

            status_code = self._status_code(
                response, operation, safe_endpoint, sends
            )
            if status_code == 401:
                if auth_replayed or sends >= MAX_CONTENT_SENDS:
                    raise self._http_error(
                        operation, safe_endpoint, status_code, sends
                    )
                auth_replayed = True
                self._invalidate_access_token(token)
                token = self._get_access_token()
                continue

            if status_code in RETRYABLE_STATUS_CODES:
                if (
                    transient_retries >= MAX_TRANSIENT_RETRIES
                    or sends >= MAX_CONTENT_SENDS
                ):
                    raise self._http_error(
                        operation, safe_endpoint, status_code, sends
                    )
                if not self._sleep_for_retry(transient_retries, response):
                    raise self._http_error(
                        operation,
                        safe_endpoint,
                        status_code,
                        sends,
                        retry_after_too_large=True,
                    )
                transient_retries += 1
                continue

            if not 200 <= status_code < 300:
                raise self._http_error(
                    operation, safe_endpoint, status_code, sends
                )
            return response, sends

        raise QuranApiTransportError(operation, safe_endpoint, sends)

    def _send_content_request(
        self,
        endpoint: str,
        params: Mapping[str, Any] | None,
        token: str,
    ) -> Any | None:
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
        return response

    def _status_code(
        self,
        response: Any,
        operation: str,
        endpoint: str,
        attempts: int,
    ) -> int:
        status_code: Any | None = None
        try:
            status_code = getattr(response, "status_code", None)
        except Exception:  # noqa: BLE001 - response objects are untrusted
            status_code = None
        if (
            isinstance(status_code, bool)
            or not isinstance(status_code, int)
            or not 100 <= status_code <= 599
        ):
            raise QuranApiPayloadError(
                operation,
                endpoint,
                attempts,
                "missing a valid HTTP status",
            )
        return status_code

    def _sleep_for_retry(
        self, transient_retries: int, response: Any | None
    ) -> bool:
        retry_after = (
            _response_header(response, "Retry-After")
            if response is not None
            else None
        )
        if retry_after is not None and _RETRY_AFTER_DELTA_PATTERN.fullmatch(
            retry_after.strip()
        ):
            delay = float(retry_after.strip())
            if delay > MAX_RETRY_WAIT_SECONDS:
                return False
        else:
            jitter = 0.0
            sampled: Any | None = None
            try:
                sampled = self._random_source()
            except Exception:  # noqa: BLE001 - retry jitter must not break requests
                sampled = None
            if (
                isinstance(sampled, (int, float))
                and not isinstance(sampled, bool)
                and math.isfinite(sampled)
            ):
                jitter = min(1.0, max(0.0, float(sampled)))
            base_delay = _INITIAL_BACKOFF_SECONDS * (2**transient_retries)
            delay = min(
                MAX_RETRY_WAIT_SECONDS,
                base_delay + (base_delay * 0.25 * jitter),
            )
        self._sleeper(delay)
        return True

    @staticmethod
    def _http_error(
        operation: str,
        endpoint: str,
        status_code: int,
        attempts: int,
        *,
        retry_after_too_large: bool = False,
    ) -> QuranApiHttpError:
        if retry_after_too_large:
            guidance = (
                "The server requested a wait longer than 30 seconds; "
                "try again later."
            )
        elif status_code == 401:
            guidance = "Authentication was rejected; verify the API credentials."
        elif status_code == 429 or status_code >= 500:
            guidance = "The service is temporarily unavailable; try again later."
        else:
            guidance = "Check the request and API credentials."
        return QuranApiHttpError(
            operation,
            endpoint,
            status_code,
            attempts,
            guidance=guidance,
        )

    @staticmethod
    def _json_payload(
        response: Any,
        operation: str,
        endpoint: str,
        attempts: int,
    ) -> Mapping[str, Any]:
        if not _has_json_content_type(response):
            raise QuranApiPayloadError(
                operation,
                endpoint,
                attempts,
                "expected an application/json Content-Type",
            )

        payload: Any = _INVALID_JSON
        try:
            payload = response.json()
        except (TypeError, ValueError):
            payload = _INVALID_JSON
        if payload is _INVALID_JSON:
            raise QuranApiPayloadError(
                operation, endpoint, attempts, "invalid JSON"
            ) from None
        if not isinstance(payload, Mapping):
            raise QuranApiPayloadError(
                operation,
                endpoint,
                attempts,
                "invalid payload: JSON value is not an object",
            )
        return payload

    def api_call(
        self, endpoint: str, translation_resource_ids: Sequence[str] = ()
    ) -> Mapping[str, Any]:
        """Call one supported Content API endpoint and return its JSON object."""

        params: Mapping[str, Any] | None = None
        if endpoint.lstrip("/").startswith("verses/"):
            params = {
                "words": 1,
                "word_fields": "text_uthmani",
            }
            if translation_resource_ids:
                params = {
                    **params,
                    "translations": ",".join(translation_resource_ids),
                }

        response, attempts = self._content_request(endpoint, params)
        safe_endpoint = _safe_endpoint(endpoint)
        payload = self._json_payload(
            response,
            "Quran Foundation Content API",
            safe_endpoint,
            attempts,
        )

        normalized_endpoint = safe_endpoint.lstrip("/")
        problem: str | None = None
        if normalized_endpoint.startswith("verses/by_key/"):
            problem = _verse_payload_problem(payload, translation_resource_ids)
        elif re.fullmatch(r"chapters/[0-9]+", normalized_endpoint):
            problem = _chapter_payload_problem(payload)
        if problem is not None:
            raise QuranApiPayloadError(
                "Quran Foundation Content API",
                safe_endpoint,
                attempts,
                problem,
            )
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
