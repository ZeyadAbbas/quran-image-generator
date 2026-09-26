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
    QuranApiHttpError,
    QuranApiPayloadError,
    QuranApiTransportError,
    QuranContentClient,
)


class FakeResponse:
    def __init__(
        self,
        status_code=200,
        payload=None,
        json_error=None,
        headers=None,
    ):
        self.status_code = status_code
        self.payload = {} if payload is None else payload
        self.json_error = json_error
        self.headers = (
            {"Content-Type": "application/json"}
            if headers is None
            else headers
        )
        self.json_calls = 0

    def json(self):
        self.json_calls += 1
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


def content_response(status_code=200, payload=None, headers=None):
    return FakeResponse(
        status_code=status_code,
        payload=payload,
        headers=headers,
    )


def make_client(
    session,
    *,
    environment="prelive",
    monotonic=lambda: 0.0,
    sleeper=lambda _seconds: None,
    random_source=lambda: 0.0,
    timeout=(5, 30),
):
    return QuranContentClient(
        QuranApiConfig(environment, "client-id", "client-secret"),
        session=session,
        monotonic=monotonic,
        sleeper=sleeper,
        random_source=random_source,
        timeout=timeout,
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
    assert token_kwargs["timeout"] == (5.0, 30.0)

    assert session.get_calls == [
        (
            "https://apis-prelive.quran.foundation/content/api/v4/chapters",
            {
                "headers": {
                    "Accept": "application/json",
                    "x-auth-token": "access-token",
                    "x-client-id": "client-id",
                },
                "timeout": (5.0, 30.0),
            },
        )
    ]


def test_verse_request_has_only_verse_parameters():
    session = FakeSession(
        token_results=[token_response()],
        content_results=[
            content_response(
                payload={
                    "verse": {
                        "verse_number": 1,
                        "verse_key": "1:1",
                        "words": [],
                        "translations": [
                            {"resource_id": 131, "text": "translation"},
                            {"resource_id": 31, "text": "translation"},
                        ],
                    }
                }
            )
        ],
    )

    payload = make_client(session).api_call(
        "/verses/by_key/1:1", ("131", "31")
    )

    assert payload["verse"]["verse_key"] == "1:1"
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
                "timeout": (5.0, 30.0),
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
            content_response(payload={"chapter": {"name_simple": "Al-Fatihah"}}),
        ],
    )

    assert make_client(session).api_call("chapters/1") == {
        "chapter": {"name_simple": "Al-Fatihah"}
    }
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


def test_permanent_content_failure_is_not_retried():
    session = FakeSession(
        token_results=[token_response()],
        content_results=[content_response(status_code=403)],
    )

    with pytest.raises(QuranApiHttpError, match="HTTP 403"):
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

    token_failure = requests.RequestException(
        f"{client_secret} {access_token} {basic_header}"
    )
    token_session = FakeSession(
        token_results=[token_failure, token_failure, token_failure],
        content_results=[],
    )
    with pytest.raises(QuranApiTransportError) as token_error:
        QuranContentClient(
            config,
            session=token_session,
            sleeper=lambda _seconds: None,
            random_source=lambda: 0.0,
        ).api_call("chapters")

    content_failure = requests.RequestException(
        f"{client_secret} {access_token} {basic_header}"
    )
    content_session = FakeSession(
        token_results=[token_response(access_token)],
        content_results=[content_failure, content_failure, content_failure],
    )
    with pytest.raises(QuranApiTransportError) as content_error:
        QuranContentClient(
            config,
            session=content_session,
            sleeper=lambda _seconds: None,
            random_source=lambda: 0.0,
        ).api_call("chapters")

    for error in (token_error.value, content_error.value):
        rendered = f"{error!s} {error!r}"
        assert client_id not in rendered
        assert client_secret not in rendered
        assert access_token not in rendered
        assert basic_header not in rendered
        assert error.__context__ is None


def test_transient_content_failures_retry_with_deterministic_backoff():
    sleeps = []
    session = FakeSession(
        token_results=[token_response()],
        content_results=[
            content_response(status_code=503),
            requests.Timeout("sentinel-timeout-detail"),
            content_response(payload={"chapters": []}),
        ],
    )

    assert make_client(session, sleeper=sleeps.append).api_call("chapters") == {
        "chapters": []
    }
    assert len(session.get_calls) == 3
    assert sleeps == [0.5, 1.0]


@pytest.mark.parametrize("status_code", [400, 403, 404, 422])
def test_permanent_client_errors_never_retry(status_code):
    sleeps = []
    session = FakeSession(
        token_results=[token_response()],
        content_results=[content_response(status_code=status_code)],
    )

    with pytest.raises(QuranApiHttpError) as caught:
        make_client(session, sleeper=sleeps.append).api_call("chapters")

    assert caught.value.status_code == status_code
    assert caught.value.attempts == 1
    assert len(session.get_calls) == 1
    assert sleeps == []


@pytest.mark.parametrize(
    "failure",
    [requests.Timeout("timeout"), requests.ConnectionError("connection")],
)
def test_transport_failures_stop_after_three_attempts_without_final_sleep(failure):
    sleeps = []
    session = FakeSession(
        token_results=[token_response()],
        content_results=[failure, failure, failure],
    )

    with pytest.raises(QuranApiTransportError) as caught:
        make_client(session, sleeper=sleeps.append).api_call("chapters")

    assert caught.value.attempts == 3
    assert len(session.get_calls) == 3
    assert sleeps == [0.5, 1.0]
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "statuses",
    [
        (503, 401, 503, 200),
        (401, 503, 503, 200),
    ],
)
def test_transient_and_401_budgets_share_four_content_sends(statuses):
    sleeps = []
    session = FakeSession(
        token_results=[token_response("first"), token_response("second")],
        content_results=[
            content_response(
                status_code=status_code,
                payload={"chapters": []} if status_code == 200 else None,
            )
            for status_code in statuses
        ],
    )

    assert make_client(session, sleeper=sleeps.append).api_call("chapters") == {
        "chapters": []
    }
    assert len(session.get_calls) == 4
    assert len(session.post_calls) == 2
    assert sleeps == [0.5, 1.0]


def test_absolute_content_send_cap_prevents_a_fifth_attempt():
    sleeps = []
    session = FakeSession(
        token_results=[token_response("first"), token_response("second")],
        content_results=[
            content_response(status_code=401),
            content_response(status_code=503),
            content_response(status_code=503),
            content_response(status_code=503),
            content_response(payload={"must": "not be sent"}),
        ],
    )

    with pytest.raises(QuranApiHttpError) as caught:
        make_client(session, sleeper=sleeps.append).api_call("chapters")

    assert caught.value.status_code == 503
    assert caught.value.attempts == 4
    assert len(session.get_calls) == 4
    assert sleeps == [0.5, 1.0]


@pytest.mark.parametrize(
    ("retry_after", "expected_sleep"),
    [("7", 7.0), ("0", 0.0), ("not-a-delay", 0.5), ("-1", 0.5)],
)
def test_retry_after_delta_or_fallback_is_deterministic(
    retry_after, expected_sleep
):
    sleeps = []
    session = FakeSession(
        token_results=[token_response()],
        content_results=[
            content_response(
                status_code=429,
                headers={
                    "Content-Type": "text/html",
                    "Retry-After": retry_after,
                },
            ),
            content_response(payload={"chapters": []}),
        ],
    )

    assert make_client(session, sleeper=sleeps.append).api_call("chapters") == {
        "chapters": []
    }
    assert sleeps == [expected_sleep]


def test_retry_after_above_cap_fails_without_sleep_or_retry():
    sleeps = []
    response = content_response(
        status_code=429,
        headers={"Retry-After": "31", "Content-Type": "text/plain"},
    )
    session = FakeSession(
        token_results=[token_response()],
        content_results=[response],
    )

    with pytest.raises(QuranApiHttpError, match="longer than 30 seconds"):
        make_client(session, sleeper=sleeps.append).api_call("chapters")

    assert len(session.get_calls) == 1
    assert response.json_calls == 0
    assert sleeps == []


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "application/json"},
        {"content-type": "Application/JSON; Charset=UTF-8"},
        {"CONTENT-TYPE": "application/vnd.quran+json; charset=utf-8"},
        {"Content-Type": "APPLICATION/PROBLEM+JSON"},
    ],
)
def test_json_content_types_are_accepted_case_insensitively(headers):
    session = FakeSession(
        token_results=[token_response()],
        content_results=[
            content_response(payload={"chapters": []}, headers=headers)
        ],
    )

    assert make_client(session).api_call("chapters") == {"chapters": []}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Content-Type": "text/html"}, {"Content-Type": "text/json"}],
)
def test_missing_or_wrong_content_type_stops_before_json(headers):
    response = content_response(payload={"secret": "sentinel-body"}, headers=headers)
    session = FakeSession(
        token_results=[token_response()],
        content_results=[response],
    )

    with pytest.raises(QuranApiPayloadError, match="Content-Type") as caught:
        make_client(session).api_call("chapters")

    assert response.json_calls == 0
    assert "sentinel-body" not in f"{caught.value!s} {caught.value!r}"


def test_http_status_is_checked_before_content_type_or_json():
    response = FakeResponse(
        status_code=422,
        payload={"body": "sentinel-body"},
        json_error=ValueError("sentinel-decoder"),
        headers={"Content-Type": "text/html", "X-Sentinel": "sentinel-header"},
    )
    session = FakeSession(
        token_results=[token_response("sentinel-token")],
        content_results=[response],
    )

    with pytest.raises(QuranApiHttpError) as caught:
        make_client(session).api_call("chapters?token=sentinel-query")

    rendered = f"{caught.value!s} {caught.value!r}"
    assert response.json_calls == 0
    assert caught.value.endpoint == "/chapters"
    for sentinel in (
        "sentinel-body",
        "sentinel-decoder",
        "sentinel-header",
        "sentinel-token",
        "sentinel-query",
    ):
        assert sentinel not in rendered


def test_non_mapping_content_payload_has_a_sanitized_payload_error():
    session = FakeSession(
        token_results=[token_response()],
        content_results=[content_response(payload=["sentinel-body"])],
    )

    with pytest.raises(QuranApiPayloadError, match="not an object") as caught:
        make_client(session).api_call("chapters")

    assert "sentinel-body" not in f"{caught.value!s} {caught.value!r}"
    assert caught.value.__context__ is None


def test_custom_connect_and_read_timeouts_reach_both_endpoints():
    session = FakeSession(
        token_results=[token_response()],
        content_results=[content_response(payload={"chapters": []})],
    )

    assert make_client(session, timeout=(1.25, 9.5)).api_call("chapters") == {
        "chapters": []
    }
    assert session.post_calls[0][1]["timeout"] == (1.25, 9.5)
    assert session.get_calls[0][1]["timeout"] == (1.25, 9.5)


@pytest.mark.parametrize(
    "timeout",
    [
        (),
        (1,),
        (1, 2, 3),
        (0, 1),
        (1, -1),
        (1, float("inf")),
        (True, 1),
        ("5", 30),
    ],
)
def test_timeout_pair_members_are_validated(timeout):
    with pytest.raises(ValueError, match="positive finite"):
        make_client(FakeSession(), timeout=timeout)


def test_scalar_timeout_remains_compatible_but_is_passed_as_a_pair():
    session = FakeSession(
        token_results=[token_response()],
        content_results=[content_response(payload={})],
    )

    assert make_client(session, timeout=4).api_call("chapters") == {}
    assert session.post_calls[0][1]["timeout"] == (4.0, 4.0)
    assert session.get_calls[0][1]["timeout"] == (4.0, 4.0)


def test_token_acquisition_retries_transient_status_and_transport_failure():
    sleeps = []
    session = FakeSession(
        token_results=[
            content_response(status_code=503),
            requests.ConnectionError("sentinel-secret"),
            token_response("eventual-token"),
        ],
        content_results=[content_response(payload={"chapters": []})],
    )

    assert make_client(session, sleeper=sleeps.append).api_call("chapters") == {
        "chapters": []
    }
    assert len(session.post_calls) == 3
    assert sleeps == [0.5, 1.0]


def test_token_retry_cap_has_no_final_sleep():
    sleeps = []
    session = FakeSession(
        token_results=[
            content_response(status_code=503),
            content_response(status_code=503),
            content_response(status_code=503),
        ],
        content_results=[],
    )

    with pytest.raises(QuranApiHttpError) as caught:
        make_client(session, sleeper=sleeps.append).api_call("chapters")

    assert caught.value.attempts == 3
    assert len(session.post_calls) == 3
    assert sleeps == [0.5, 1.0]


def test_jitter_source_is_injected_and_bounded():
    sleeps = []
    session = FakeSession(
        token_results=[token_response()],
        content_results=[
            content_response(status_code=500),
            content_response(status_code=502),
            content_response(payload={}),
        ],
    )

    assert make_client(
        session,
        sleeper=sleeps.append,
        random_source=lambda: 1.0,
    ).api_call("chapters") == {}
    assert sleeps == [0.625, 1.25]
