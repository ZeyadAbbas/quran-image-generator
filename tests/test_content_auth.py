from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
import requests
from requests.auth import HTTPBasicAuth

from quran_image_generator.content import (
    QURAN_FOUNDATION_ACCESS_URL,
    QuranApiConfig,
    QuranApiConfigurationError,
    QuranApiError,
    QuranContentClient,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self.payload = {} if payload is None else payload
        self.json_error = json_error

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class FakeSession:
    def __init__(self, *, token_results=(), content_results=()):
        self.token_results = deque(token_results)
        self.content_results = deque(content_results)
        self.post_calls = []
        self.get_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        result = self.token_results.popleft()
        if isinstance(result, BaseException):
            raise result
        return result

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        result = self.content_results.popleft()
        if isinstance(result, BaseException):
            raise result
        return result


def token_response(token="access-token", **overrides):
    payload = {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 3600,
    }
    payload.update(overrides)
    return FakeResponse(payload=payload)


def content_response(status_code=200, payload=None):
    return FakeResponse(status_code=status_code, payload=payload)


def make_client(session, *, environment="prelive", monotonic=lambda: 0.0):
    return QuranContentClient(
        QuranApiConfig(environment, "client-id", "client-secret"),
        session=session,
        monotonic=monotonic,
    )


@pytest.mark.parametrize(
    ("value", "environment", "auth_url", "content_url"),
    [
        (
            None,
            "prelive",
            "https://prelive-oauth2.quran.foundation",
            "https://apis-prelive.quran.foundation/content/api/v4",
        ),
        (
            "",
            "prelive",
            "https://prelive-oauth2.quran.foundation",
            "https://apis-prelive.quran.foundation/content/api/v4",
        ),
        (
            " PRELIVE ",
            "prelive",
            "https://prelive-oauth2.quran.foundation",
            "https://apis-prelive.quran.foundation/content/api/v4",
        ),
        (
            "Production",
            "production",
            "https://oauth2.quran.foundation",
            "https://apis.quran.foundation/content/api/v4",
        ),
    ],
)
def test_environment_selects_an_atomic_endpoint_pair(
    value, environment, auth_url, content_url
):
    environ = {
        "QF_CLIENT_ID": "client-id",
        "QF_CLIENT_SECRET": "client-secret",
    }
    if value is not None:
        environ["QF_ENV"] = value

    config = QuranApiConfig.from_environment(environ)

    assert config.environment == environment
    assert config.auth_base_url == auth_url
    assert config.content_base_url == content_url


@pytest.mark.parametrize("value", ["prod", "pre-live", "staging", "local"])
def test_invalid_environment_is_rejected(value):
    with pytest.raises(QuranApiConfigurationError, match="prelive.*production"):
        QuranApiConfig.from_environment(
            {
                "QF_CLIENT_ID": "client-id",
                "QF_CLIENT_SECRET": "client-secret",
                "QF_ENV": value,
            }
        )


@pytest.mark.parametrize(
    ("environ", "missing"),
    [
        ({}, ("QF_CLIENT_ID", "QF_CLIENT_SECRET")),
        ({"QF_CLIENT_ID": "client-id"}, ("QF_CLIENT_SECRET",)),
        ({"QF_CLIENT_SECRET": "secret-value"}, ("QF_CLIENT_ID",)),
        (
            {"QF_CLIENT_ID": "  ", "QF_CLIENT_SECRET": "\t"},
            ("QF_CLIENT_ID", "QF_CLIENT_SECRET"),
        ),
    ],
)
def test_missing_credentials_fail_early_with_access_instructions(environ, missing):
    with pytest.raises(QuranApiConfigurationError) as caught:
        QuranContentClient.from_environment(environ)

    message = str(caught.value)
    assert all(name in message for name in missing)
    assert QURAN_FOUNDATION_ACCESS_URL in message
    assert "secret-value" not in message


def test_token_and_chapter_requests_match_the_official_contract():
    session = FakeSession(
        token_results=[token_response()],
        content_results=[content_response(payload={"chapters": []})],
    )
    client = QuranContentClient.from_environment(
        {
            "QF_CLIENT_ID": "client-id",
            "QF_CLIENT_SECRET": "client-secret",
            "QF_ENV": "prelive",
        },
        session=session,
        monotonic=lambda: 100.0,
    )

    assert client.api_call("chapters") == {"chapters": []}

    assert len(session.post_calls) == 1
    token_url, token_kwargs = session.post_calls[0]
    assert token_url == "https://prelive-oauth2.quran.foundation/oauth2/token"
    assert isinstance(token_kwargs["auth"], HTTPBasicAuth)
    assert token_kwargs["auth"].username == "client-id"
    assert token_kwargs["auth"].password == "client-secret"
    assert token_kwargs["headers"] == {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    assert token_kwargs["data"] == {
        "grant_type": "client_credentials",
        "scope": "content",
    }
    assert token_kwargs["timeout"] == 30

    assert session.get_calls == [
        (
            "https://apis-prelive.quran.foundation/content/api/v4/chapters",
            {
                "headers": {
                    "Accept": "application/json",
                    "x-auth-token": "access-token",
                    "x-client-id": "client-id",
                },
                "timeout": 30,
            },
        )
    ]


def test_verse_request_has_only_verse_parameters():
    session = FakeSession(
        token_results=[token_response()],
        content_results=[content_response(payload={"verse": {}})],
    )

    payload = make_client(session).api_call(
        "/verses/by_key/1:1", ("131", "31")
    )

    assert payload == {"verse": {}}
    assert session.get_calls == [
        (
            (
                "https://apis-prelive.quran.foundation/content/api/v4/"
                "verses/by_key/1:1"
            ),
            {
                "headers": {
                    "Accept": "application/json",
                    "x-auth-token": "access-token",
                    "x-client-id": "client-id",
                },
                "params": {
                    "translations": "131,31",
                    "words": 1,
                    "word_fields": "text_uthmani",
                },
                "timeout": 30,
            },
        )
    ]
    prepared = requests.Request(
        "GET",
        session.get_calls[0][0],
        params=session.get_calls[0][1]["params"],
    ).prepare()
    assert "words=1" in prepared.url.split("?", maxsplit=1)[1].split("&")


def test_token_is_reused_then_refreshed_at_the_expiry_margin():
    now = [0.0]
    session = FakeSession(
        token_results=[token_response("first"), token_response("second")],
        content_results=[
            content_response(payload={}),
            content_response(payload={}),
            content_response(payload={}),
        ],
    )
    client = make_client(session, monotonic=lambda: now[0])

    client.api_call("chapters")
    now[0] = 3569.0
    client.api_call("chapters")
    now[0] = 3570.0
    client.api_call("chapters")

    assert len(session.post_calls) == 2
    assert [
        kwargs["headers"]["x-auth-token"] for _, kwargs in session.get_calls
    ] == ["first", "first", "second"]


@pytest.mark.parametrize("timeout", [None, 0, -1, float("inf"), float("nan")])
def test_request_timeout_must_be_positive_and_finite(timeout):
    with pytest.raises(ValueError, match="positive finite"):
        QuranContentClient(
            QuranApiConfig("prelive", "client-id", "client-secret"),
            session=FakeSession(),
            timeout=timeout,
        )


def test_concurrent_calls_share_one_token_refresh():
    class BlockingSession:
        def __init__(self):
            self.started = Event()
            self.release = Event()
            self.post_calls = 0

        def post(self, url, **kwargs):
            self.post_calls += 1
            self.started.set()
            assert self.release.wait(timeout=2)
            return token_response()

        def get(self, url, **kwargs):
            return content_response(payload={})

    session = BlockingSession()
    client = make_client(session)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(client.api_call, "chapters")
        assert session.started.wait(timeout=2)
        second = executor.submit(client.api_call, "chapters")
        session.release.set()
        assert first.result(timeout=2) == {}
        assert second.result(timeout=2) == {}

    assert session.post_calls == 1


def test_one_401_invalidates_the_token_and_replays_once():
    session = FakeSession(
        token_results=[token_response("first"), token_response("second")],
        content_results=[
            content_response(status_code=401),
            content_response(payload={"chapter": {}}),
        ],
    )

    assert make_client(session).api_call("chapters/1") == {"chapter": {}}
    assert len(session.post_calls) == 2
    assert [
        kwargs["headers"]["x-auth-token"] for _, kwargs in session.get_calls
    ] == ["first", "second"]


def test_second_401_stops_without_another_replay():
    session = FakeSession(
        token_results=[token_response("first"), token_response("second")],
        content_results=[
            content_response(status_code=401),
            content_response(status_code=401),
        ],
    )

    with pytest.raises(QuranApiError, match="HTTP 401"):
        make_client(session).api_call("chapters")

    assert len(session.post_calls) == 2
    assert len(session.get_calls) == 2


def test_non_401_content_failure_is_not_retried():
    session = FakeSession(
        token_results=[token_response()],
        content_results=[content_response(status_code=503)],
    )

    with pytest.raises(QuranApiError, match="HTTP 503"):
        make_client(session).api_call("chapters")

    assert len(session.post_calls) == 1
    assert len(session.get_calls) == 1


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"expires_in": 3600}, "access_token"),
        ({"access_token": "", "expires_in": 3600}, "access_token"),
        (
            {
                "access_token": "sentinel-access-token",
                "token_type": "mac",
                "expires_in": 3600,
            },
            "token_type",
        ),
        ({"access_token": "sentinel-access-token"}, "expires_in"),
        (
            {"access_token": "sentinel-access-token", "expires_in": 0},
            "expires_in",
        ),
        (
            {"access_token": "sentinel-access-token", "expires_in": True},
            "expires_in",
        ),
        (
            {"access_token": "sentinel-access-token", "expires_in": "3600"},
            "expires_in",
        ),
        (
            {
                "access_token": "sentinel-access-token",
                "expires_in": float("inf"),
            },
            "expires_in",
        ),
        (["not", "an", "object"], "invalid payload"),
    ],
)
def test_malformed_token_payload_is_rejected_without_leaking_it(payload, message):
    session = FakeSession(
        token_results=[FakeResponse(payload=payload)],
        content_results=[],
    )

    with pytest.raises(QuranApiError, match=message) as caught:
        make_client(session).api_call("chapters")

    rendered = f"{caught.value!s} {caught.value!r}"
    assert "sentinel-access-token" not in rendered


def test_token_type_is_optional_and_case_insensitive():
    for payload in (
        {"access_token": "token", "expires_in": 3600},
        {
            "access_token": "token",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    ):
        session = FakeSession(
            token_results=[FakeResponse(payload=payload)],
            content_results=[content_response(payload={})],
        )
        assert make_client(session).api_call("chapters") == {}


def test_invalid_token_json_is_sanitized():
    session = FakeSession(
        token_results=[
            FakeResponse(json_error=ValueError("sentinel-access-token"))
        ],
        content_results=[],
    )

    with pytest.raises(QuranApiError, match="invalid JSON") as caught:
        make_client(session).api_call("chapters")

    assert "sentinel-access-token" not in repr(caught.value)
    assert caught.value.__context__ is None


def test_invalid_content_json_is_sanitized_without_retaining_the_decoder_error():
    session = FakeSession(
        token_results=[token_response("sentinel-access-token")],
        content_results=[
            FakeResponse(json_error=ValueError("sentinel-access-token"))
        ],
    )

    with pytest.raises(QuranApiError, match="invalid JSON") as caught:
        make_client(session).api_call("chapters")

    assert "sentinel-access-token" not in repr(caught.value)
    assert caught.value.__context__ is None


def test_configuration_and_network_errors_do_not_expose_credentials_or_tokens():
    client_id = "sentinel-client-id"
    client_secret = "sentinel-client-secret"
    access_token = "sentinel-access-token"
    basic_header = "Authorization: Basic sentinel-basic-value"
    config = QuranApiConfig("prelive", client_id, client_secret)

    assert client_id not in repr(config)
    assert client_secret not in repr(config)

    token_session = FakeSession(
        token_results=[
            requests.RequestException(
                f"{client_secret} {access_token} {basic_header}"
            )
        ],
        content_results=[],
    )
    with pytest.raises(QuranApiError) as token_error:
        QuranContentClient(config, session=token_session).api_call("chapters")

    content_session = FakeSession(
        token_results=[token_response(access_token)],
        content_results=[
            requests.RequestException(
                f"{client_secret} {access_token} {basic_header}"
            )
        ],
    )
    with pytest.raises(QuranApiError) as content_error:
        QuranContentClient(config, session=content_session).api_call("chapters")

    for error in (token_error.value, content_error.value):
        rendered = f"{error!s} {error!r}"
        assert client_id not in rendered
        assert client_secret not in rendered
        assert access_token not in rendered
        assert basic_header not in rendered
        assert error.__context__ is None
