"""Failing integration tests for server startup (User Story 2 / T015).

These tests verify the ``schwab-mcp serve`` subcommand (``cli_main(["serve"])``) using
a stubbed/fake schwabdev Client and fake MCPServer (no network, no real MCP
transport).

The module-level import below WILL raise ``ImportError`` because
``schwab_mcp.server`` imports ``from mcp.server import MCPServer`` and the
real ``mcp`` package exposes ``Server``, not ``MCPServer`` — every test in
this file fails at import time during the TDD red phase for T015.

After the server module is fixed to use the real ``mcp.Server`` API, these
tests should pass and cover:

1. Valid store → client constructed with ``tokens_db`` from config and a
   ``call_on_auth`` hook that raises ``ReauthorizationRequiredError`` (no
   browser / prompt in serve context — FR-001).
2. One proactive ``linked_accounts()`` read happens BEFORE the MCP stdio
   transport connects (assert ordering; FR-013, SC-004).
3. Absent store → no client constructed at all, exit ``4`` before any MCP
   handshake.
4. Expired access token with valid refresh → silent automatic renewal (no
   interactive hook invocation), ``renewal_success`` event emitted.
5. Store with ``SCHWAB_TOKEN_DB`` custom path honoured (FR-012).
6. Server registers **zero** MCP tools in this feature (assert the server
   exposes no tools via ``list_tools()``).

References
----------
- FR-001: Explicit auth command, never implicit.
- FR-009: Token-store peek before client construction.
- FR-012: Custom token DB path honoured.
- FR-013: Proactive access validation before MCP handshake.
- FR-014: Auth events on stderr.
- SC-004: Headless server startup sequence.
- contracts/cli.md : CLI exit codes and behaviour.
- contracts/events.md : Auth event line format.
"""

from __future__ import annotations

import itertools
import os
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

# ---------------------------------------------------------------------------
# This import WILL raise ImportError because server.py uses MCPServer which
# does NOT exist in mcp.server (the real API is Server).  Every test in this
# file fails at import time during the TDD red phase.
# ---------------------------------------------------------------------------
from schwab_mcp.cli import main as cli_main

# ---------------------------------------------------------------------------
# Call-sequence recorder — used by fakes to let tests assert ordering
# ---------------------------------------------------------------------------

_call_sequence: list[tuple] = []
_call_counter = itertools.count()


def _reset_call_sequence() -> None:
    _call_sequence.clear()
    _call_counter = itertools.count()


def _record(call_name: str, *args: Any) -> None:
    _call_sequence.append((next(_call_counter), call_name) + args)


# ---------------------------------------------------------------------------
# Fake schwabdev Client — mirrors the subset of schwabdev.v4.Client that
# cli_main(["serve"]) interacts with.
# ---------------------------------------------------------------------------


class FakeSchwabdevClient:
    """A stubbed schwabdev Client for testing the serve flow.

    Tracks whether ``linked_accounts()`` has been called and whether
    ``call_on_auth`` was ever invoked.  Optionally simulates expired-token /
    auto-renewal behaviour.
    """

    _instances: list[FakeSchwabdevClient] = []

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        callback_url: str,
        tokens_db: str | os.PathLike = "",
        call_on_auth: Callable[[str], str] | None = None,
        open_browser_for_auth: bool = False,
        **kwargs: Any,
    ) -> None:
        _record("Client.__init__", str(tokens_db))
        self.app_key = app_key
        self.app_secret = app_secret
        self.callback_url = callback_url
        self.tokens_db = str(tokens_db)
        self.call_on_auth = call_on_auth
        self.open_browser_for_auth = open_browser_for_auth
        self.linked_accounts_call_count: int = 0
        # When True, simulate silent token renewal on linked_accounts()
        # without invoking call_on_auth.
        self.tokens_expired: bool = False
        FakeSchwabdevClient._instances.append(self)

    def linked_accounts(self) -> dict[str, Any]:
        _record("linked_accounts")
        self.linked_accounts_call_count += 1
        return {"accounts": [{"accountNumber": "12345678", "type": "MARGIN"}]}

    @classmethod
    def reset(cls) -> None:
        cls._instances.clear()


# ---------------------------------------------------------------------------
# Fake MCPServer — intercepts MCPServer construction and run_stdio_async so
# the test can assert ordering and tool registration without a real MCP
# transport.
# ---------------------------------------------------------------------------


class FakeMCPServer:
    """Stub for ``mcp.server.MCPServer`` (the name used in server.py).

    The real ``mcp`` package uses ``Server``, so ``MCPServer`` does not exist
    yet — this fake provides the shape ``cli_main(["serve"])`` expects.
    """

    _instances: list[FakeMCPServer] = []

    def __init__(self, name: str) -> None:
        _record("MCPServer.__init__", name)
        self.name = name
        self._tools: list[Any] = []
        FakeMCPServer._instances.append(self)

    async def run_stdio_async(self) -> None:
        """Non-blocking stub — returns immediately."""
        _record("MCPServer.run_stdio_async")

    def list_tools(self) -> list[Any]:
        """Return the list of registered tools."""
        return list(self._tools)

    @classmethod
    def reset(cls) -> None:
        cls._instances.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token_db(path: Path) -> Path:
    """Create a valid schwabdev SQLite token store at *path*.

    The schema matches what the real schwabdev library creates: a
    ``schwabdev`` table with access/refresh/id tokens.
    """
    import sqlite3

    con = sqlite3.connect(str(path))
    try:
        con.execute(
            "CREATE TABLE schwabdev ("
            "  access_token TEXT,"
            "  refresh_token TEXT,"
            "  id_token TEXT,"
            "  access_token_issued TEXT,"
            "  refresh_token_issued TEXT,"
            "  expires_in INTEGER,"
            "  token_type TEXT,"
            "  scope TEXT"
            ")"
        )
        con.execute(
            "INSERT INTO schwabdev VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "fake-access-token",
                "fake-refresh-token",
                "fake-id-token",
                "2026-10-19T12:00:00Z",
                "2026-10-19T12:00:00Z",
                1800,
                "Bearer",
                "readonly",
            ),
        )
        con.commit()
    finally:
        con.close()
    return path


def _make_expired_token_db(path: Path) -> Path:
    """Create a token store with an expired access token but valid refresh.

    The ``access_token_issued`` timestamp is set far in the past so that
    ``expires_in`` (1800s = 30 min) has long elapsed.
    """
    import sqlite3

    con = sqlite3.connect(str(path))
    try:
        con.execute(
            "CREATE TABLE schwabdev ("
            "  access_token TEXT,"
            "  refresh_token TEXT,"
            "  id_token TEXT,"
            "  access_token_issued TEXT,"
            "  refresh_token_issued TEXT,"
            "  expires_in INTEGER,"
            "  token_type TEXT,"
            "  scope TEXT"
            ")"
        )
        con.execute(
            "INSERT INTO schwabdev VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "expired-access-token",
                "valid-refresh-token",
                "expired-id-token",
                "2024-01-01T00:00:00Z",  # 2+ years in the past
                "2026-10-19T12:00:00Z",  # refresh still fresh
                1800,
                "Bearer",
                "readonly",
            ),
        )
        con.commit()
    finally:
        con.close()
    return path


def _capture_stderr_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    """Install a print hook that captures stderr lines and returns the list."""
    captured: list[str] = []

    def tracking_print(*args: Any, **kwargs: Any) -> None:
        file = kwargs.get("file", sys.stdout)
        text = " ".join(str(a) for a in args)
        if file is sys.stderr:
            captured.append(text)

    monkeypatch.setattr("builtins.print", tracking_print)
    return captured


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _default_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Set up a clean environment with valid but fake credentials."""
    monkeypatch.setenv("SCHWAB_APP_KEY", "TEST_APP_KEY_32CHARS__FILLER")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "TEST_APP_SECRET_32CHAR_FILLER")
    monkeypatch.setenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1")
    token_db = str(tmp_path / "tokens.db")
    monkeypatch.setenv("SCHWAB_TOKEN_DB", token_db)
    tmp_path.mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
def _reset_fakes() -> None:
    """Reset all fake class-level state before each test."""
    _reset_call_sequence()
    FakeSchwabdevClient.reset()
    FakeMCPServer.reset()


@pytest.fixture(autouse=True)
def _patch_mcp_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``mcp.server.MCPServer`` with our fake so server.py can
    import it.  Without this patch the import in server.py fails because
    the real ``mcp.server`` module exports ``Server``, not ``MCPServer``.
    """
    monkeypatch.setattr("schwab_mcp.server.MCPServer", FakeMCPServer)


# ===================================================================
# 1. Valid store → client constructed with guard hook (FR-001)
# ===================================================================


class TestValidStoreStartsServe:
    """With a valid token store, ``serve`` constructs the schwabdev client
    with a ``call_on_auth`` guard hook that raises ``ReauthorizationRequiredError``
    — never opening a browser or prompting (FR-001)."""

    def test_client_constructed_with_guard_hook(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A valid store causes the client to be instantiated with a
        ``call_on_auth`` hook that raises ``ReauthorizationRequiredError``."""
        _make_token_db(tmp_path / "tokens.db")

        monkeypatch.setattr(
            "schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit) as exc_info:
            cli_main(["serve"])

        assert exc_info.value.code == 0, (
            f"Expected exit code 0 on successful serve startup, "
            f"got {exc_info.value.code}"
        )

        # A FakeSchwabdevClient must have been constructed
        assert len(FakeSchwabdevClient._instances) == 1, (
            "Expected exactly one FakeSchwabdevClient to be constructed"
        )

        client = FakeSchwabdevClient._instances[0]
        assert client.call_on_auth is not None, (
            "The client must be constructed with a call_on_auth hook "
            "(FR-001 — no browser/prompt in serve context)"
        )

        # The guard hook must raise ReauthorizationRequiredError
        with pytest.raises(Exception) as hook_exc:
            client.call_on_auth("https://example.com/auth")

        from schwab_mcp.errors import ReauthorizationRequiredError

        assert type(hook_exc.value) is ReauthorizationRequiredError, (
            "The call_on_auth guard hook must raise "
            "ReauthorizationRequiredError, not a generic Exception"
        )

    def test_guard_hook_message_includes_auth_command(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The guard hook's error message must tell the owner to run
        ``schwab-mcp auth``."""
        _make_token_db(tmp_path / "tokens.db")

        monkeypatch.setattr(
            "schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        client = FakeSchwabdevClient._instances[0]
        try:
            client.call_on_auth("https://example.com/auth")
        except Exception as exc:
            message = str(exc)
            assert "schwab-mcp auth" in message, (
                "Guard hook message must instruct the owner to run "
                f"'schwab-mcp auth', got: {message!r}"
            )

    def test_tokens_db_path_passed_to_client(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The ``tokens_db`` argument passed to the client must match the
        configured ``SCHWAB_TOKEN_DB`` path."""
        token_db = _make_token_db(tmp_path / "tokens.db")

        monkeypatch.setattr(
            "schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        client = FakeSchwabdevClient._instances[0]
        expected = os.fsdecode(token_db)
        assert os.path.normpath(client.tokens_db) == os.path.normpath(expected), (
            f"Expected client.tokens_db to be {expected!r}, "
            f"got {client.tokens_db!r}"
        )


# ===================================================================
# 2. linked_accounts() called BEFORE MCP transport connects (FR-013, SC-004)
# ===================================================================


class TestLinkedAccountsOrdering:
    """``linked_accounts()`` must be called at least once *before* the MCP
    stdio transport connection (FR-013, SC-004)."""

    def test_linked_accounts_called_before_run_stdio(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The call to ``linked_accounts()`` must appear in the call
        sequence *before* ``MCPServer.run_stdio_async``."""
        _make_token_db(tmp_path / "tokens.db")

        monkeypatch.setattr(
            "schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        # Find positions of key events in the call sequence
        linked_accounts_pos: int | None = None
        run_stdio_pos: int | None = None

        for seq_no, call_name, *args in _call_sequence:
            if call_name == "linked_accounts":
                linked_accounts_pos = seq_no
            elif call_name == "MCPServer.run_stdio_async":
                run_stdio_pos = seq_no

        assert linked_accounts_pos is not None, (
            "linked_accounts() was never called"
        )
        assert run_stdio_pos is not None, (
            "MCPServer.run_stdio_async() was never called"
        )
        assert linked_accounts_pos < run_stdio_pos, (
            f"linked_accounts() (position {linked_accounts_pos}) must be "
            f"called BEFORE MCPServer.run_stdio_async() (position "
            f"{run_stdio_pos}) — FR-013, SC-004"
        )

    def test_linked_accounts_called_exactly_once(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``linked_accounts()`` should be called exactly once during
        startup (the proactive check)."""
        _make_token_db(tmp_path / "tokens.db")

        monkeypatch.setattr(
            "schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        client = FakeSchwabdevClient._instances[0]
        assert client.linked_accounts_call_count == 1, (
            f"Expected linked_accounts() to be called exactly 1 time, "
            f"got {client.linked_accounts_call_count}"
        )

    def test_mcp_server_constructed_after_linked_accounts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The MCPServer itself must be constructed *after*
        ``linked_accounts()`` succeeds."""
        _make_token_db(tmp_path / "tokens.db")

        monkeypatch.setattr(
            "schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        linked_accounts_pos: int | None = None
        mcp_init_pos: int | None = None

        for seq_no, call_name, *args in _call_sequence:
            if call_name == "linked_accounts":
                linked_accounts_pos = seq_no
            elif call_name == "MCPServer.__init__":
                mcp_init_pos = seq_no

        assert linked_accounts_pos is not None
        assert mcp_init_pos is not None
        assert linked_accounts_pos < mcp_init_pos, (
            f"linked_accounts() (position {linked_accounts_pos}) must be "
            f"called BEFORE MCPServer.__init__() (position {mcp_init_pos})"
        )


# ===================================================================
# 3. Absent store → exit 4, no client constructed (FR-001, FR-009)
# ===================================================================


class TestAbsentStoreFailsFast:
    """When the token store is absent, ``serve`` must exit with code 4
    *before* constructing any schwabdev client or MCP server."""

    def test_absent_store_exits_code_4(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No token store → exit 4 (``ReauthorizationRequiredError``)."""
        # Deliberately NOT creating a token store
        monkeypatch.setattr(
            "schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit) as exc_info:
            cli_main(["serve"])

        assert exc_info.value.code == 4, (
            f"Expected exit code 4 for absent store, "
            f"got {exc_info.value.code}"
        )

    def test_absent_store_no_client_constructed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No token store → no FakeSchwabdevClient should be constructed."""
        monkeypatch.setattr(
            "schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        assert len(FakeSchwabdevClient._instances) == 0, (
            "No FakeSchwabdevClient should be constructed when the token "
            "store is absent (FR-001, FR-009)"
        )

    def test_absent_store_no_mcp_server(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No token store → no FakeMCPServer should be constructed."""
        monkeypatch.setattr(
            "schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        assert len(FakeMCPServer._instances) == 0, (
            "No FakeMCPServer should be constructed when the token store "
            "is absent"
        )

    def test_absent_store_exit_before_call_on_auth(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When the store is absent, ``call_on_auth`` must NEVER be invoked
        (FR-001 — no implicit auth in serve context).  Exit must happen
        before any auth hook could fire."""
        hook_invoked: list[str] = []

        def tracking_hook(auth_url: str) -> str:
            hook_invoked.append(auth_url)
            return ""

        monkeypatch.setattr(
            "schwabdev.Client",
            lambda *a, **kw: FakeSchwabdevClient(*a, **kw, call_on_auth=tracking_hook),
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        assert len(hook_invoked) == 0, (
            "call_on_auth must NOT be invoked when the store is absent "
            "(FR-001 — exit before any auth attempt)"
        )


# ===================================================================
# 4. Expired access token → silent automatic renewal
# ===================================================================


class TestExpiredTokenAutoRenewal:
    """When the token store has an expired access token but a valid refresh
    token, the server must silently renew (no ``call_on_auth`` invocation)
    and emit ``renewal_success`` events."""

    def test_expired_token_does_not_trigger_call_on_auth(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """An expired access token with a valid refresh must auto-renew
        without calling the interactive ``call_on_auth`` hook."""
        _make_expired_token_db(tmp_path / "tokens.db")

        hook_invoked: list[str] = []

        def tracking_hook(auth_url: str) -> str:
            hook_invoked.append(auth_url)
            return ""

        def tracking_client(*a: Any, **kw: Any) -> FakeSchwabdevClient:
            # Remove the guard hook so we can inject our tracking hook.
            kw.pop("call_on_auth", None)
            return FakeSchwabdevClient(*a, **kw, call_on_auth=tracking_hook)

        monkeypatch.setattr(
            "schwabdev.Client",
            tracking_client,
        )

        with pytest.raises(SystemExit) as exc_info:
            cli_main(["serve"])

        assert exc_info.value.code == 0, (
            f"Expected exit code 0 after successful auto-renewal, "
            f"got {exc_info.value.code}"
        )
        assert len(hook_invoked) == 0, (
            "call_on_auth must NOT be invoked during silent auto-renewal "
            "of an expired access token"
        )

    def test_expired_token_renewal_success_event(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When auto-renewal succeeds, ``renewal_success`` events must be
        emitted on stderr (FR-014)."""
        _make_expired_token_db(tmp_path / "tokens.db")

        captured_stderr = _capture_stderr_lines(monkeypatch)

        monkeypatch.setattr(
            "schwabdev.Client",
            lambda *a, **kw: FakeSchwabdevClient(*a, **kw, tokens_expired=True),
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        stderr_text = "\n".join(captured_stderr)
        events_found = [
            line for line in captured_stderr
            if "auth_event=renewal_success" in line
        ]

        assert len(events_found) >= 1, (
            "Expected at least one 'auth_event=renewal_success' in stderr "
            f"after auto-renewal, got:\n{stderr_text}"
        )

    def test_expired_token_linked_accounts_still_called(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Even with an expired token, ``linked_accounts()`` must still
        be called as part of proactive access validation (FR-013)."""
        _make_expired_token_db(tmp_path / "tokens.db")

        monkeypatch.setattr(
            "schwabdev.Client",
            lambda *a, **kw: FakeSchwabdevClient(*a, **kw, tokens_expired=True),
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        client = FakeSchwabdevClient._instances[0]
        assert client.linked_accounts_call_count >= 1, (
            "linked_accounts() must be called even when the token is "
            "expired (FR-013 — proactive validation)"
        )


# ===================================================================
# 5. Custom SCHWAB_TOKEN_DB path honoured (FR-012)
# ===================================================================


class TestCustomTokenDbPath:
    """The ``SCHWAB_TOKEN_DB`` environment variable must be honoured
    exactly (FR-012)."""

    def test_custom_path_used_for_peek(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A custom ``SCHWAB_TOKEN_DB`` path must be used by
        ``peek_store()`` and passed to the client."""
        custom_dir = tmp_path / "custom" / "path"
        custom_dir.mkdir(parents=True)
        custom_db = custom_dir / "my_tokens.db"
        _make_token_db(custom_db)

        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(custom_db))
        monkeypatch.setattr(
            "schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        assert len(FakeSchwabdevClient._instances) == 1, (
            "Client should have been constructed when a token store "
            "exists at the custom path"
        )

        client = FakeSchwabdevClient._instances[0]
        assert os.path.normpath(client.tokens_db) == os.path.normpath(
            os.fsdecode(custom_db)
        ), (
            f"Expected client.tokens_db to be {custom_db!r}, "
            f"got {client.tokens_db!r}"
        )

    def test_custom_path_absent_exits_code_4(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When ``SCHWAB_TOKEN_DB`` points to a non-existent file, the
        server must exit with code 4 (ReauthorizationRequiredError)."""
        custom_dir = tmp_path / "other"
        custom_dir.mkdir(parents=True)
        missing_db = custom_dir / "missing.db"

        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(missing_db))
        monkeypatch.setattr(
            "schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit) as exc_info:
            cli_main(["serve"])

        assert exc_info.value.code == 4, (
            f"Expected exit code 4 when custom path points to "
            f"non-existent file, got {exc_info.value.code}"
        )
        assert len(FakeSchwabdevClient._instances) == 0, (
            "No client should be constructed when the token store at the "
            "custom path is absent"
        )


# ===================================================================
# 6. Zero MCP tools registered in this feature
# ===================================================================


class TestZeroTools:
    """The server startup (this feature) must register zero MCP tools.
    Tools arrive in a later feature."""

    def test_no_tools_after_startup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """After ``cli_main(["serve"])`` completes, the MCPServer must expose no
        tools via ``list_tools()``."""
        _make_token_db(tmp_path / "tokens.db")

        monkeypatch.setattr(
            "schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        assert len(FakeMCPServer._instances) == 1, (
            "Expected exactly one MCPServer to be created"
        )
        mcp = FakeMCPServer._instances[0]
        tools = mcp.list_tools()
        assert len(tools) == 0, (
            f"Expected zero MCP tools after serve startup, "
            f"got {len(tools)}: {tools}"
        )
        assert tools == [], (
            f"Expected empty tool list, got {tools}"
        )

    def test_server_object_created_with_correct_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The MCPServer must be created with the name ``schwab-mcp``."""
        _make_token_db(tmp_path / "tokens.db")

        monkeypatch.setattr(
            "schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        assert len(FakeMCPServer._instances) == 1
        mcp = FakeMCPServer._instances[0]
        assert mcp.name == "schwab-mcp", (
            f"Expected MCPServer name 'schwab-mcp', got {mcp.name!r}"
        )


# ===================================================================
# 7. Error event on connectivity failure
# ===================================================================


class TestConnectivityFailure:
    """When ``linked_accounts()`` fails (e.g. network down), the server
    must emit ``renewal_failure`` and exit with error code 7."""

    def test_connectivity_failure_exits_code_7(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A network error during ``linked_accounts()`` must result in
        exit code 7 (``ConnectivityError``)."""
        _make_token_db(tmp_path / "tokens.db")

        class FailingSchwabdevClient(FakeSchwabdevClient):
            def linked_accounts(self) -> dict[str, Any]:
                _record("linked_accounts")
                self.linked_accounts_call_count += 1
                raise RuntimeError("Simulated network failure")

        monkeypatch.setattr(
            "schwabdev.Client", FailingSchwabdevClient
        )

        with pytest.raises(SystemExit) as exc_info:
            cli_main(["serve"])

        assert exc_info.value.code == 7, (
            f"Expected exit code 7 for connectivity failure, "
            f"got {exc_info.value.code}"
        )

    def test_connectivity_failure_emits_renewal_failure_event(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A network error during ``linked_accounts()`` must emit a
        ``renewal_failure`` event with ``outcome=connectivity`` on stderr."""
        _make_token_db(tmp_path / "tokens.db")

        captured_stderr = _capture_stderr_lines(monkeypatch)

        class FailingSchwabdevClient(FakeSchwabdevClient):
            def linked_accounts(self) -> dict[str, Any]:
                _record("linked_accounts")
                self.linked_accounts_call_count += 1
                raise RuntimeError("Simulated network failure")

        monkeypatch.setattr(
            "schwabdev.Client", FailingSchwabdevClient
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        stderr_text = "\n".join(captured_stderr)
        assert "auth_event=renewal_failure" in stderr_text, (
            "Expected 'auth_event=renewal_failure' in stderr output "
            f"on connectivity failure, got:\n{stderr_text}"
        )
        assert "outcome=connectivity" in stderr_text, (
            "Expected 'outcome=connectivity' in stderr output "
            f"on connectivity failure, got:\n{stderr_text}"
        )

    def test_no_renewal_success_before_validation_outcome(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """contracts/events.md (T027): ``renewal_success`` marks a
        *succeeded* refresh/validation.  A connectivity failure must NEVER
        be preceded by a ``renewal_success`` line — the event stream must
        not claim success and then failure for the same startup."""
        _make_token_db(tmp_path / "tokens.db")

        captured_stderr = _capture_stderr_lines(monkeypatch)

        class FailingSchwabdevClient(FakeSchwabdevClient):
            def linked_accounts(self) -> dict[str, Any]:
                _record("linked_accounts")
                self.linked_accounts_call_count += 1
                raise RuntimeError("Simulated network failure")

        monkeypatch.setattr(
            "schwabdev.Client", FailingSchwabdevClient
        )

        with pytest.raises(SystemExit):
            cli_main(["serve"])

        stderr_text = "\n".join(captured_stderr)
        assert "auth_event=renewal_success" not in stderr_text, (
            "renewal_success must not be emitted before the validation "
            f"outcome is known (got renewal_success + renewal_failure):\n{stderr_text}"
        )

    def test_exactly_one_renewal_success_on_valid_startup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """contracts/events.md (T027): ``renewal_success`` is emitted once
        per successful startup validation — not for auxiliary transitions
        like "access token loaded from store" or "server reaching ready
        state"."""
        _make_token_db(tmp_path / "tokens.db")

        captured_stderr = _capture_stderr_lines(monkeypatch)
        monkeypatch.setattr("schwabdev.Client", FakeSchwabdevClient)

        with pytest.raises(SystemExit) as exc_info:
            cli_main(["serve"])

        assert exc_info.value.code == 0
        stderr_text = "\n".join(captured_stderr)
        count = stderr_text.count("auth_event=renewal_success")
        assert count == 1, (
            f"Expected exactly ONE renewal_success per successful startup "
            f"validation (contracts/events.md), got {count}:\n{stderr_text}"
        )
        assert "auth_event=renewal_failure" not in stderr_text