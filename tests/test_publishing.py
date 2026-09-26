from __future__ import annotations

import builtins
import io
import logging
import sys
from pathlib import Path
from types import ModuleType

import pytest

from quran_image_generator.publishing import (
    INSTAGRAM_PASSWORD_ENV,
    INSTAGRAM_USERNAME_ENV,
    InstagramCredentials,
    InstagramPublisher,
    PublishingError,
    PublishTarget,
    resolve_instagram_credentials,
)


class InteractiveInput(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_credentials_repr_never_contains_secrets():
    credentials = InstagramCredentials(
        username="sentinel-username", password="sentinel-password"
    )

    representation = repr(credentials)

    assert "sentinel-username" not in representation
    assert "sentinel-password" not in representation
    assert "sentinel-username" not in repr(InstagramPublisher(credentials))
    assert "sentinel-password" not in repr(InstagramPublisher(credentials))


def test_environment_credentials_take_precedence_without_prompts():
    def unexpected_prompt(prompt: str) -> str:
        pytest.fail(f"unexpected credential prompt: {prompt}")

    credentials = resolve_instagram_credentials(
        {
            INSTAGRAM_USERNAME_ENV: "environment-user",
            INSTAGRAM_PASSWORD_ENV: "environment-password",
        },
        stdin=io.StringIO(),
        input_fn=unexpected_prompt,
        getpass_fn=unexpected_prompt,
    )

    assert credentials.username == "environment-user"
    assert credentials.password == "environment-password"


def test_tty_prompts_only_for_missing_environment_field():
    prompts: list[str] = []

    def unexpected_username_prompt(prompt: str) -> str:
        pytest.fail(f"username should come from the environment: {prompt}")

    def password_prompt(prompt: str) -> str:
        prompts.append(prompt)
        return "prompted-password"

    credentials = resolve_instagram_credentials(
        {INSTAGRAM_USERNAME_ENV: "environment-user"},
        stdin=InteractiveInput(),
        input_fn=unexpected_username_prompt,
        getpass_fn=password_prompt,
    )

    assert credentials.username == "environment-user"
    assert credentials.password == "prompted-password"
    assert prompts == ["Instagram password: "]


def test_tty_prompts_for_username_then_hidden_password():
    prompts: list[str] = []

    credentials = resolve_instagram_credentials(
        {},
        stdin=InteractiveInput(),
        input_fn=lambda prompt: prompts.append(prompt) or "prompted-user",
        getpass_fn=lambda prompt: prompts.append(prompt) or "prompted-password",
    )

    assert credentials.username == "prompted-user"
    assert credentials.password == "prompted-password"
    assert prompts == ["Instagram username: ", "Instagram password: "]


def test_non_tty_missing_credentials_fails_without_prompting():
    def unexpected_prompt(prompt: str) -> str:
        pytest.fail(f"non-interactive credential prompt: {prompt}")

    with pytest.raises(PublishingError) as caught:
        resolve_instagram_credentials(
            {},
            stdin=io.StringIO(),
            input_fn=unexpected_prompt,
            getpass_fn=unexpected_prompt,
        )

    message = str(caught.value)
    assert INSTAGRAM_USERNAME_ENV in message
    assert INSTAGRAM_PASSWORD_ENV in message
    assert "interactive terminal" in message


def test_prompt_failures_discard_secret_bearing_exception_context():
    sentinel = "sentinel-prompt-secret"

    def failing_prompt(prompt: str) -> str:
        raise RuntimeError(f"prompt failed with {sentinel}")

    with pytest.raises(PublishingError) as caught:
        resolve_instagram_credentials(
            {},
            stdin=InteractiveInput(),
            input_fn=failing_prompt,
            getpass_fn=failing_prompt,
        )

    assert sentinel not in f"{caught.value!s} {caught.value!r}"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    ("target", "expected_event"),
    [
        (PublishTarget.POST, ("post", "quran")),
        (PublishTarget.STORY, ("story", None)),
    ],
)
def test_instagram_adapter_dispatches_each_target_once(
    tmp_path: Path, target: PublishTarget, expected_event: tuple[str, str | None]
):
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"retained image")
    events: list[tuple[object, ...]] = []

    class FakeClient:
        def login(self, username: str, password: str) -> bool:
            events.append(("login", username, password))
            return True

        def photo_upload(self, path: Path, caption: str) -> None:
            events.append(("post", path, caption))

        def photo_upload_to_story(self, path: Path) -> None:
            events.append(("story", path))

    publisher = InstagramPublisher(
        InstagramCredentials("sentinel-user", "sentinel-password"), FakeClient
    )

    publisher.publish(image_path, target)

    assert events[0] == ("login", "sentinel-user", "sentinel-password")
    if expected_event[0] == "post":
        assert events[1:] == [("post", image_path, expected_event[1])]
    else:
        assert events[1:] == [("story", image_path)]


def test_invalid_target_is_rejected_before_client_creation(tmp_path: Path):
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"retained image")

    def unexpected_client():
        pytest.fail("invalid target must be rejected before client creation")

    publisher = InstagramPublisher(
        InstagramCredentials("user", "password"), unexpected_client
    )

    with pytest.raises(PublishingError, match="must be 'post' or 'story'"):
        publisher.publish(image_path, "feed")  # type: ignore[arg-type]


def test_incomplete_direct_credentials_are_rejected_before_client_creation(
    tmp_path: Path,
):
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"retained image")

    def unexpected_client():
        pytest.fail("incomplete credentials must be rejected before client creation")

    publisher = InstagramPublisher(InstagramCredentials("", ""), unexpected_client)

    with pytest.raises(PublishingError) as caught:
        publisher.publish(image_path, PublishTarget.POST)

    assert INSTAGRAM_USERNAME_ENV in str(caught.value)
    assert INSTAGRAM_PASSWORD_ENV in str(caught.value)


def test_missing_optional_dependency_has_install_guidance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"retained image")
    real_import = builtins.__import__

    def import_without_instagram(name, *args, **kwargs):
        if name == "instagrapi":
            raise ImportError("sentinel-import-detail")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_instagram)
    publisher = InstagramPublisher(InstagramCredentials("user", "password"))

    with pytest.raises(PublishingError) as caught:
        publisher.publish(image_path, PublishTarget.POST)

    message = str(caught.value)
    assert ".[instagram]" in message
    assert "sentinel-import-detail" not in message
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert image_path.is_file()


def test_real_adapter_path_disables_client_loggers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"retained image")
    clients = []

    class FakeClient:
        def __init__(self, *, logger):
            self.logger = logger
            self.private_request_logger = logging.getLogger("unsafe-default")
            clients.append(self)

        def login(self, username: str, password: str) -> bool:
            return True

        def photo_upload(self, path: Path, caption: str) -> None:
            return None

    fake_module = ModuleType("instagrapi")
    fake_module.Client = FakeClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "instagrapi", fake_module)

    InstagramPublisher(InstagramCredentials("user", "password")).publish(
        image_path, PublishTarget.POST
    )

    assert len(clients) == 1
    logger = clients[0].logger
    assert logger.disabled is True
    assert logger.propagate is False
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], logging.NullHandler)
    assert clients[0].private_request_logger is logger


@pytest.mark.parametrize("failure_stage", ["client", "login", "upload"])
def test_dependency_failures_are_sanitized_and_keep_output(
    tmp_path: Path, failure_stage: str
):
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"retained image")
    secrets = ("sentinel-user", "sentinel-password", "sentinel-session-token")

    class FakeClient:
        def login(self, username: str, password: str) -> bool:
            if failure_stage == "login":
                raise RuntimeError(" ".join(secrets))
            return True

        def photo_upload(self, path: Path, caption: str) -> None:
            raise RuntimeError(" ".join(secrets))

    def client_factory():
        if failure_stage == "client":
            raise RuntimeError(" ".join(secrets))
        return FakeClient()

    publisher = InstagramPublisher(
        InstagramCredentials(secrets[0], secrets[1]), client_factory
    )

    with pytest.raises(PublishingError) as caught:
        publisher.publish(image_path, PublishTarget.POST)

    rendered_error = f"{caught.value!s} {caught.value!r}"
    assert all(secret not in rendered_error for secret in secrets)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert image_path.read_bytes() == b"retained image"


def test_false_login_result_is_an_authentication_failure(tmp_path: Path):
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"retained image")

    class FakeClient:
        def login(self, username: str, password: str) -> bool:
            return False

        def photo_upload(self, path: Path, caption: str) -> None:
            pytest.fail("upload must not run after a rejected login")

    publisher = InstagramPublisher(InstagramCredentials("user", "password"), FakeClient)

    with pytest.raises(PublishingError, match="authentication failed"):
        publisher.publish(image_path, PublishTarget.POST)


@pytest.mark.parametrize(
    ("error_type_name", "expected_message"),
    [
        ("ChallengeRequired", "requires account verification"),
        ("ClientConnectionError", "could not be reached"),
        ("ClientRequestTimeout", "could not be reached"),
    ],
)
def test_challenge_and_network_failures_have_safe_guidance(
    tmp_path: Path, error_type_name: str, expected_message: str
):
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"retained image")
    failure_type = type(error_type_name, (RuntimeError,), {})

    class FakeClient:
        def login(self, username: str, password: str) -> bool:
            raise failure_type("sentinel-session-token")

    publisher = InstagramPublisher(
        InstagramCredentials("sentinel-user", "sentinel-password"), FakeClient
    )

    with pytest.raises(PublishingError) as caught:
        publisher.publish(image_path, PublishTarget.POST)

    assert expected_message in str(caught.value)
    assert "sentinel" not in f"{caught.value!s} {caught.value!r}"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
