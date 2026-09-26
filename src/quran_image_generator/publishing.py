"""Optional publishing services for generated images.

This module intentionally depends only on the Python standard library.  The
Instagram client is imported only when a caller explicitly publishes an image.
"""

from __future__ import annotations

import getpass
import logging
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, TextIO

INSTAGRAM_USERNAME_ENV = "QIG_INSTAGRAM_USERNAME"
INSTAGRAM_PASSWORD_ENV = "QIG_INSTAGRAM_PASSWORD"


class PublishTarget(str, Enum):
    """Supported Instagram destinations."""

    POST = "post"
    STORY = "story"


@dataclass(frozen=True, slots=True)
class InstagramCredentials:
    """Credentials whose values are deliberately omitted from representations."""

    username: str = field(repr=False)
    password: str = field(repr=False)


class PublishingError(RuntimeError):
    """A safe, user-facing publishing failure."""


class _MissingInstagramDependency(PublishingError):
    """Internal signal with safe installation guidance."""


class Publisher(Protocol):
    """Minimal boundary implemented by an image publisher."""

    def publish(self, image_path: Path, target: PublishTarget) -> None:
        """Publish one retained local image to ``target``."""


def _discarding_logger() -> logging.Logger:
    """Return a logger that cannot emit or propagate Instagram client data."""

    logger = logging.getLogger("quran_image_generator.instagram")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    logger.disabled = True
    return logger


def _reraise_client_exception(_client: Any, error: BaseException) -> None:
    """Stop instagrapi from entering its automatic challenge resolver."""

    raise error


def _reject_interactive_handler(*_args: Any, **_kwargs: Any) -> None:
    """Prevent optional-client fallbacks from reading secrets interactively."""

    raise RuntimeError("Interactive Instagram challenge handling is disabled.")


def _failure_category(error: BaseException) -> str:
    """Classify optional-client failures without retaining their payloads."""

    class_names = {error_type.__name__ for error_type in type(error).__mro__}
    if any("Challenge" in name for name in class_names):
        return "challenge"
    if class_names & {
        "ClientConnectionError",
        "ClientIncompleteReadError",
        "ClientRequestTimeout",
        "ChunkedEncodingError",
        "ConnectionError",
        "Timeout",
    }:
        return "network"
    return "other"


def _failure_message(category: str, stage: str, path: Path) -> str:
    retained = f"The generated image remains available at: {path}"
    if category == "challenge":
        return (
            "Instagram requires account verification. Complete the checkpoint "
            f"in the official Instagram app or website, then retry. {retained}"
        )
    if category == "network":
        return (
            "Instagram could not be reached. Check the network connection and "
            f"retry. {retained}"
        )
    return f"Instagram {stage} failed. {retained}"


def _is_interactive(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, OSError):
        return False


def resolve_instagram_credentials(
    environ: Mapping[str, str] | None = None,
    *,
    stdin: TextIO | None = None,
    input_fn: Callable[[str], str] | None = None,
    getpass_fn: Callable[[str], str] | None = None,
    allow_prompt: bool = True,
) -> InstagramCredentials:
    """Resolve Instagram credentials from the environment, then TTY prompts.

    Environment values take precedence independently.  Missing values are only
    prompted for when standard input is interactive, so automation cannot hang.
    """

    source = os.environ if environ is None else environ
    username = source.get(INSTAGRAM_USERNAME_ENV, "").strip()
    password = source.get(INSTAGRAM_PASSWORD_ENV, "")
    missing = [
        name
        for name, value in (
            (INSTAGRAM_USERNAME_ENV, username),
            (INSTAGRAM_PASSWORD_ENV, password),
        )
        if not value
    ]
    if not missing:
        return InstagramCredentials(username=username, password=password)

    input_stream = sys.stdin if stdin is None else stdin
    if not allow_prompt or not _is_interactive(input_stream):
        names = " and ".join(missing)
        guidance = (
            "Set the environment variable(s)."
            if not allow_prompt
            else "Set the environment variable(s), or run the command in an "
            "interactive terminal."
        )
        raise PublishingError(
            f"Missing Instagram credentials: {names}. {guidance}"
        )

    read_username = input if input_fn is None else input_fn
    read_password = getpass.getpass if getpass_fn is None else getpass_fn
    prompt_cancelled = False
    prompt_failed = False
    try:
        if not username:
            username = read_username("Instagram username: ").strip()
        if not password:
            password = read_password("Instagram password: ")
    except (EOFError, KeyboardInterrupt):
        prompt_cancelled = True
    except Exception:  # noqa: BLE001 - discard any prompt implementation details
        prompt_failed = True
    if prompt_cancelled:
        raise PublishingError("Instagram credential entry was cancelled.")
    if prompt_failed:
        raise PublishingError("Instagram credentials could not be read safely.")

    missing = [
        name
        for name, value in (
            (INSTAGRAM_USERNAME_ENV, username),
            (INSTAGRAM_PASSWORD_ENV, password),
        )
        if not value
    ]
    if missing:
        names = " and ".join(missing)
        raise PublishingError(f"Missing Instagram credentials: {names}.")
    return InstagramCredentials(username=username, password=password)


@dataclass(slots=True)
class InstagramPublisher:
    """Publish images with the optional ``instagrapi`` dependency."""

    credentials: InstagramCredentials = field(repr=False)
    client_factory: Callable[[], Any] | None = field(default=None, repr=False)

    def _create_client(self) -> Any:
        if self.client_factory is not None:
            return self.client_factory()
        client_class: Any | None = None
        try:
            from instagrapi import Client
        except ImportError:
            pass
        else:
            client_class = Client
        if client_class is None:
            raise _MissingInstagramDependency(
                "Instagram publishing support is not installed. Install it with "
                "`python -m pip install 'quran-image-generator[instagram]'` "
                "(or `python -m pip install '.[instagram]'` from a source checkout)."
            )
        logger = _discarding_logger()
        client = client_class(logger=logger)
        client.logger = logger
        client.private_request_logger = logger
        client.handle_exception = _reraise_client_exception
        client.challenge_code_handler = _reject_interactive_handler
        client.change_password_handler = _reject_interactive_handler
        return client

    def publish(self, image_path: Path, target: PublishTarget) -> None:
        """Publish exactly once, converting dependency failures to safe errors."""

        invalid_target = False
        try:
            resolved_target = PublishTarget(target)
        except (TypeError, ValueError):
            invalid_target = True
            resolved_target = PublishTarget.POST
        if invalid_target:
            raise PublishingError("Instagram publish target must be 'post' or 'story'.")

        if not self.credentials.username.strip() or not self.credentials.password:
            raise PublishingError(
                "Instagram credentials are incomplete. Set "
                f"{INSTAGRAM_USERNAME_ENV} and {INSTAGRAM_PASSWORD_ENV}, or use "
                "an interactive terminal."
            )

        path = Path(image_path)
        if not path.is_file():
            raise PublishingError(
                "Instagram publishing was not attempted because the generated "
                f"image could not be found at: {path}"
            )

        dependency_error: _MissingInstagramDependency | None = None
        initialization_failure: str | None = None
        client: Any | None = None
        try:
            client = self._create_client()
        except _MissingInstagramDependency as error:
            dependency_error = error
        except Exception as error:  # noqa: BLE001 - redact every third-party failure
            initialization_failure = _failure_category(error)
        if dependency_error is not None:
            raise dependency_error
        if initialization_failure is not None or client is None:
            raise PublishingError(
                _failure_message(
                    initialization_failure or "other", "client initialization", path
                )
            )

        authenticated: Any = None
        authentication_failure: str | None = None
        try:
            authenticated = client.login(
                self.credentials.username, self.credentials.password
            )
        except Exception as error:  # noqa: BLE001 - redact every third-party failure
            authentication_failure = _failure_category(error)
        if authentication_failure is not None or authenticated is False:
            raise PublishingError(
                _failure_message(
                    authentication_failure or "other", "authentication", path
                )
            )

        upload_failure: str | None = None
        try:
            if resolved_target is PublishTarget.POST:
                client.photo_upload(path, "quran")
            else:
                client.photo_upload_to_story(path)
        except Exception as error:  # noqa: BLE001 - redact every third-party failure
            upload_failure = _failure_category(error)
        if upload_failure is not None:
            raise PublishingError(_failure_message(upload_failure, "upload", path))
