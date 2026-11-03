"""Unit tests for the shared schwabdev client factory (bug spx-delta-timeout).

All entry points (``serve``, ``auth``, ``renew``) must construct the
schwabdev client through one factory so that the configured provider
request ``timeout`` (``Config.request_timeout``) is applied everywhere —
schwabdev's 10 s default breaks full-chain fetches at large
``strikeCount`` ($SPX + ``delta_target``).
"""

from __future__ import annotations

from typing import Any

import pytest
import schwabdev

from schwab_mcp.client import build_schwab_client
from schwab_mcp.config import Config


class RecordingClient:
    """Stand-in for ``schwabdev.Client`` that records constructor args."""

    instances: list[tuple[tuple, dict]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        RecordingClient.instances.append((args, kwargs))


@pytest.fixture(autouse=True)
def _reset_instances() -> None:
    RecordingClient.instances.clear()


@pytest.fixture()
def config() -> Config:
    return Config(
        app_key="test_key",
        app_secret="test_secret",
        callback_url="https://127.0.0.1",
        token_db="/tmp/tokens.db",
    )


def _make_client(config: Config, call_on_auth: Any = None) -> Any:
    return build_schwab_client(config, config.token_db, call_on_auth)


class TestClientConstructionPassThrough:
    """The factory forwards every construction argument unchanged."""

    def test_positional_credentials_forwarded(self, config) -> None:
        monkey_client = pytest.MonkeyPatch()
        try:
            monkey_client.setattr(schwabdev, "Client", RecordingClient)
            _make_client(config)
            (args, kwargs) = RecordingClient.instances[0]
            assert args == ("test_key", "test_secret", "https://127.0.0.1")
            assert kwargs["tokens_db"] == "/tmp/tokens.db"
            assert kwargs["open_browser_for_auth"] is False
        finally:
            monkey_client.undo()

    def test_call_on_auth_forwarded(self, config) -> None:
        hook = lambda url: url  # noqa: E731 — trivial recording hook
        monkey_client = pytest.MonkeyPatch()
        try:
            monkey_client.setattr(schwabdev, "Client", RecordingClient)
            _make_client(config, call_on_auth=hook)
            (_args, kwargs) = RecordingClient.instances[0]
            assert kwargs["call_on_auth"] is hook
        finally:
            monkey_client.undo()


class TestClientRequestTimeout:
    """The factory must pass ``timeout=config.request_timeout`` — the
    regression that caused $SPX + ``delta_target`` read timeouts."""

    def test_timeout_uses_configured_value(self, config) -> None:
        config = Config(
            app_key="test_key",
            app_secret="test_secret",
            callback_url="https://127.0.0.1",
            token_db="/tmp/tokens.db",
            request_timeout=90,
        )
        monkey_client = pytest.MonkeyPatch()
        try:
            monkey_client.setattr(schwabdev, "Client", RecordingClient)
            _make_client(config)
            (_args, kwargs) = RecordingClient.instances[0]
            assert kwargs["timeout"] == 90
        finally:
            monkey_client.undo()

    def test_timeout_default_is_60(self, config) -> None:
        assert config.request_timeout == 60
        monkey_client = pytest.MonkeyPatch()
        try:
            monkey_client.setattr(schwabdev, "Client", RecordingClient)
            _make_client(config)
            (_args, kwargs) = RecordingClient.instances[0]
            assert kwargs["timeout"] == 60
        finally:
            monkey_client.undo()