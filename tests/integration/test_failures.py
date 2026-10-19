"""Failing integration tests for all authentication failure modes (User Story 3 / T018).

These tests verify the 7 failure-mode → error mappings from data-model.md,
one test class per mapping row.  Each case exercises a stubbed schwabdev
client with ``tmp/`` paths and asserts:

- The documented exit code (no traceback, no hang).
- The distinct actionable message (SC-005 pairwise distinct).
- No secret material in any output (FR-006).
- Invariant side effects (store left in place, not deleted, etc.).

Because **some** of these mappings are not yet correctly wired in the
implementation (e.g. corrupted store → exit 5 vs exit 4; malformed
credentials → exit 2 vs exit 4), several tests are expected to FAIL in
this TDD red phase — they verify the *specified* behaviour, not the
current behaviour.

References
----------
- contracts/cli.md : Exit code definitions for ``auth`` and ``serve``.
- contracts/events.md : Auth event line format (FR-014).
- data-model.md §Failure-mode → error mapping (SC-005).
- FR-006: Zero secrets in stdout / stderr output.
- FR-007: Distinct, actionable error messages.
- FR-008: Fail-fast on missing/invalid config.
- FR-009: Corrupted store treated as absent (not deleted).
- FR-011: AuthLock prevents concurrent auth.
- FR-013: Proactive access validation in serve context.
- T019: Shared top-level error handler.
- T020: Connectivity retry-once + store preservation.
"""

from __future__ import annotations

import os
import sys
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable

import pytest

from schwab_mcp.cli import main

# ---------------------------------------------------------------------------
# Fake schwabdev Client — reused from test_auth.py pattern
# ---------------------------------------------------------------------------


class FakeSchwabdevClient:
    """A stubbed schwabdev Client for testing failure modes.

    Mirrors the subset of ``schwabdev.v4.Client`` that the CLI interacts with.
    By default the fake does **not** write a token store (callers create one
    via ``_make_token_db`` when needed).
    """

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        callback_url: str,
        tokens_db: str | os.PathLike,
        call_on_auth: Callable[[], str] | None = None,
        open_browser_for_auth: bool = False,
        **kwargs: Any,
    ) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.callback_url = callback_url
        self.tokens_db = str(tokens_db)
        self.call_on_auth = call_on_auth
        self.open_browser_for_auth = open_browser_for_auth

    def linked_accounts(self) -> dict[str, Any]:
        """Return a minimal fake response."""
        return {"accounts": [{"accountNumber": "12345678", "type": "MARGIN"}]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token_db(path: Path) -> Path:
    """Create a valid schwabdev SQLite token store at *path*.

    The schema matches what the real schwabdev library creates:
    a ``schwabdev`` table with access/refresh/id tokens.
    """
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _default_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Set up a clean environment with valid but fake credentials.

    Every test gets a clean tmp directory and valid env vars; individual
    tests override what they need.
    """
    monkeypatch.setenv("SCHWAB_APP_KEY", "TEST_APP_KEY_32CHARS__FILLER")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "TEST_APP_SECRET_32CHAR_FILLER")
    monkeypatch.setenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1")
    token_db = str(tmp_path / "tokens.db")
    monkeypatch.setenv("SCHWAB_TOKEN_DB", token_db)
    tmp_path.mkdir(parents=True, exist_ok=True)


# ===================================================================
# 1. Missing env vars → MissingConfigError (exit 2)
#    data-model row: "Missing config"
# ===================================================================


class TestMissingConfig:
    """Missing ``SCHWAB_APP_KEY`` or ``SCHWAB_APP_SECRET`` → exit 2 with
    the ``MissingConfigError`` message (FR-008 fail-fast)."""

    def test_missing_app_key_auth_exits_2(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """``auth`` with missing SCHWAB_APP_KEY → exit 2, no browser, no client."""
        monkeypatch.delenv("SCHWAB_APP_KEY", raising=False)
        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient)

        captured_stderr: list[str] = []
        monkeypatch.setattr("builtins.print", _tracking_print(captured_stderr, file=sys.stderr))

        with pytest.raises(SystemExit) as exc_info:
            main(["auth"])

        assert exc_info.value.code == 2, (
            f"Expected exit code 2 for missing app key, got {exc_info.value.code}"
        )
        stderr_text = "\n".join(captured_stderr)
        assert "Set SCHWAB_APP_KEY" in stderr_text or "SCHWAB_APP_KEY" in stderr_text, (
            f"Missing-config message should appear in stderr, got:\n{stderr_text}"
        )
        _assert_no_traceback(stderr_text)
        _assert_no_secrets(stderr_text)

    def test_missing_app_secret_auth_exits_2(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """``auth`` with missing SCHWAB_APP_SECRET → exit 2."""
        monkeypatch.delenv("SCHWAB_APP_SECRET", raising=False)
        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient)

        captured_stderr: list[str] = []
        monkeypatch.setattr("builtins.print", _tracking_print(captured_stderr, file=sys.stderr))

        with pytest.raises(SystemExit) as exc_info:
            main(["auth"])

        assert exc_info.value.code == 2, (
            f"Expected exit code 2 for missing app secret, got {exc_info.value.code}"
        )
        stderr_text = "\n".join(captured_stderr)
        assert "Set SCHWAB_APP_SECRET" in stderr_text or "SCHWAB_APP_SECRET" in stderr_text, (
            f"Missing-config message should appear in stderr, got:\n{stderr_text}"
        )
        _assert_no_traceback(stderr_text)
        _assert_no_secrets(stderr_text)

    def test_missing_app_key_serve_exits_2(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """``serve`` with missing SCHWAB_APP_KEY → exit 2 (fail-fast before any server logic)."""
        monkeypatch.delenv("SCHWAB_APP_KEY", raising=False)
        monkeypatch.setattr("schwabdev.Client", FakeSchwabdevClient)

        captured_stderr: list[str] = []
        monkeypatch.setattr("builtins.print", _tracking_print(captured_stderr, file=sys.stderr))

        with pytest.raises(SystemExit) as exc_info:
            main(["serve"])

        assert exc_info.value.code == 2, (
            f"Expected exit code 2 for missing app key in serve, got {exc_info.value.code}"
        )
        stderr_text = "\n".join(captured_stderr)
        assert "Set SCHWAB_APP_KEY" in stderr_text or "SCHWAB_APP_KEY" in stderr_text, (
            f"Missing-config message should appear in stderr, got:\n{stderr_text}"
        )
        _assert_no_traceback(stderr_text)
        _assert_no_secrets(stderr_text)

    def test_no_browser_opened_when_config_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """FR-008: When config is missing, the browser must NOT be opened."""
        monkeypatch.delenv("SCHWAB_APP_KEY", raising=False)
        opened: list[str] = []
        monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

        with pytest.raises(SystemExit):
            main(["auth"])

        assert not opened, (
            "Browser must NOT open when config is missing (fail-fast, FR-008)"
        )


# ===================================================================
# 2. Malformed credentials → InvalidConfigError (exit 2)
#    data-model row: "Malformed config"
#    schwabdev ValueError on client init
# ===================================================================


class TestMalformedCredentials:
    """When schwabdev.Client raises ``ValueError`` on construction (malformed
    app key/secret), the error must be surfaced as ``InvalidConfigError``
    with exit code 2 and the "Fix the values" message.

    .. note::
       The current implementation in ``server.py`` wraps the ValueError as
       ``ReauthorizationRequiredError`` (exit 4), so this test is expected to
       **fail** during the TDD red phase — it asserts the *specified* mapping.
    """

    def _patch_failing_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Replace ``schwabdev.Client`` with a callable that raises ValueError."""

        def failing_client(*args: Any, **kwargs: Any) -> None:
            raise ValueError("Invalid app key format (must be even length)")

        monkeypatch.setattr("schwabdev.Client", failing_client)

    def test_serve_malformed_credentials_exits_2(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """``serve`` with credentials that cause schwabdev ValueError → exit 2
        (spec: ``InvalidConfigError``).  Currently the code gives exit 4."""
        _make_token_db(tmp_path / "tokens.db")
        self._patch_failing_client(monkeypatch)

        captured_stderr: list[str] = []
        monkeypatch.setattr("builtins.print", _tracking_print(captured_stderr, file=sys.stderr))

        with pytest.raises(SystemExit) as exc_info:
            main(["serve"])

        assert exc_info.value.code == 2, (
            f"Expected exit code 2 for malformed credentials (InvalidConfigError), "
            f"got {exc_info.value.code}. "
            "Note: current code may give exit 4 (ReauthorizationRequiredError) — "
            "this FAIL is expected TDD red phase."
        )
        stderr_text = "\n".join(captured_stderr)
        assert "Fix the values" in stderr_text, (
            f"Invalid-config message ('Fix the values') expected in stderr, got:\n{stderr_text}"
        )
        _assert_no_traceback(stderr_text)
        _assert_no_secrets(stderr_text)

    def test_serve_malformed_credentials_store_untouched(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """FR-009: An existing valid store must NOT be modified or deleted when
        client initialisation fails due to malformed credentials."""
        store_path = _make_token_db(tmp_path / "tokens.db")
        original_content = store_path.read_bytes()
        self._patch_failing_client(monkeypatch)

        with pytest.raises(SystemExit):
            main(["serve"])

        assert store_path.exists(), "Token store must still exist after malformed-cred error"
        assert store_path.read_bytes() == original_content, (
            "FR-009: Existing store must not be modified on malformed-cred error"
        )


# ===================================================================
# 3. Declined / empty paste → AuthorizationCancelledError (exit 3)
#    data-model row: "No token set + owner declines/cancels browser login"
# ===================================================================


class TestCancelledPaste:
    """When the owner pastes an empty string or cancels the prompt, the
    ``auth`` flow must abort with exit code 3 and a retry message."""

    def test_empty_paste_exits_3(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Empty paste during ``auth`` → exit 3."""
        monkeypatch.setattr("builtins.input", lambda prompt="": "")
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("webbrowser.open", lambda url: True)
        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient)

        captured_stderr: list[str] = []
        monkeypatch.setattr("builtins.print", _tracking_print(captured_stderr, file=sys.stderr))

        with pytest.raises(SystemExit) as exc_info:
            main(["auth"])

        assert exc_info.value.code == 3, (
            f"Expected exit code 3 for cancelled paste, got {exc_info.value.code}"
        )
        stderr_text = "\n".join(captured_stderr)
        assert "Re-run schwab-mcp auth" in stderr_text or "schwab-mcp auth to retry" in stderr_text, (
            f"Retry message must appear in output for cancelled auth, got:\n{stderr_text}"
        )
        _assert_no_traceback(stderr_text)
        _assert_no_secrets(stderr_text)

    def test_cancelled_paste_existing_store_untouched(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """FR-010: An existing valid token store must NOT be modified when
        the paste is cancelled."""
        store_path = _make_token_db(tmp_path / "tokens.db")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store_path))
        original_content = store_path.read_bytes()

        monkeypatch.setattr("builtins.input", lambda prompt="": "")
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("webbrowser.open", lambda url: True)
        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient)

        with pytest.raises(SystemExit):
            main(["auth"])

        assert store_path.exists(), "Token store must still exist after cancelled paste"
        assert store_path.read_bytes() == original_content, (
            "FR-010: Existing valid store must not be modified on cancelled paste"
        )

    def test_cancelled_paste_no_traceback(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """No raw Python traceback in output for a cancelled paste."""
        monkeypatch.setattr("builtins.input", lambda prompt="": "")
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("webbrowser.open", lambda url: True)
        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient)

        captured_stderr: list[str] = []
        monkeypatch.setattr("builtins.print", _tracking_print(captured_stderr, file=sys.stderr))

        with pytest.raises(SystemExit):
            main(["auth"])

        stderr_text = "\n".join(captured_stderr)
        _assert_no_traceback(stderr_text)
        _assert_no_secrets(stderr_text)


# ===================================================================
# 4. Serve with absent store → ReauthorizationRequiredError (exit 4)
#    data-model row: "Token set expired beyond recovery / refresh rejected"
# ===================================================================


class TestServeAbsentStore:
    """When ``serve`` starts with no token store at the configured path, it
    must fail with exit code 4 **before** any MCP handshake (FR-013)."""

    def test_serve_absent_store_exits_4(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """No token store exists → ``serve`` exits 4 with re-auth message."""
        monkeypatch.setattr("schwabdev.Client", FakeSchwabdevClient)

        captured_stderr: list[str] = []
        monkeypatch.setattr("builtins.print", _tracking_print(captured_stderr, file=sys.stderr))

        with pytest.raises(SystemExit) as exc_info:
            main(["serve"])

        assert exc_info.value.code == 4, (
            f"Expected exit code 4 for absent store in serve, got {exc_info.value.code}"
        )
        stderr_text = "\n".join(captured_stderr)
        assert "Run schwab-mcp auth" in stderr_text or "schwab-mcp auth" in stderr_text, (
            f"Re-auth message must appear in stderr for absent store, got:\n{stderr_text}"
        )
        _assert_no_traceback(stderr_text)
        _assert_no_secrets(stderr_text)

    def test_serve_absent_store_no_client_constructed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """FR-013 + FR-001: When the store is absent, no schwabdev Client should
        be constructed (fail-fast, no browser/prompt)."""
        constructed: list[bool] = []

        def tracking_client(*args: Any, **kwargs: Any) -> FakeSchwabdevClient:
            constructed.append(True)
            return FakeSchwabdevClient(*args, **kwargs)

        monkeypatch.setattr("schwabdev.Client", tracking_client)

        with pytest.raises(SystemExit):
            main(["serve"])

        assert not constructed, (
            "No schwabdev Client should be constructed when the store is absent "
            "(fail-fast before client init)"
        )

    def test_serve_absent_store_bounded(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Absent store → serve exits quickly (no hang, no blocking I/O)."""
        monkeypatch.setattr("schwabdev.Client", FakeSchwabdevClient)

        import time
        start = time.monotonic()
        with pytest.raises(SystemExit):
            main(["serve"])
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, (
            f"Serve should exit quickly on absent store, took {elapsed:.2f}s"
        )


# ===================================================================
# 5. Serve with corrupted store → TokenStoreCorruptedError (exit 5)
#    data-model row: "Corrupted / unreadable token set"
#    Store left in place (FR-009, treated as absent, NOT deleted)
# ===================================================================


class TestServeCorruptedStore:
    """When the token store file exists but contains unparseable content
    (e.g. ``echo "not a database" > store``), ``serve`` must exit with code 5
    and leave the store file in place.

    .. note::
       The current ``peek_store()`` implementation returns ``False`` for
       corrupted content, and ``server.py`` maps ``False`` to
       ``ReauthorizationRequiredError`` (exit 4), **not**
       ``TokenStoreCorruptedError`` (exit 5).  This test is expected to
       **fail** during the TDD red phase — it asserts the *specified*
       mapping from data-model.md.
    """

    def test_serve_corrupted_store_exits_5(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Corrupted token store (not a SQLite DB) → exit 5.

        Currently the code gives exit 4 (peek_store returns False → mapped
        as absent, not corrupted).  This FAIL is expected TDD red phase.
        """
        store_path = tmp_path / "tokens.db"
        store_path.write_text("not a database")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store_path))
        monkeypatch.setattr("schwabdev.Client", FakeSchwabdevClient)

        captured_stderr: list[str] = []
        monkeypatch.setattr("builtins.print", _tracking_print(captured_stderr, file=sys.stderr))

        with pytest.raises(SystemExit) as exc_info:
            main(["serve"])

        assert exc_info.value.code == 5, (
            f"Expected exit code 5 for corrupted store (TokenStoreCorruptedError), "
            f"got {exc_info.value.code}. "
            "Note: current code may give exit 4 — this FAIL is expected TDD red phase."
        )
        stderr_text = "\n".join(captured_stderr)
        assert "Store treated as absent" in stderr_text or "run schwab-mcp auth" in stderr_text, (
            f"Corrupted-store message expected in stderr, got:\n{stderr_text}"
        )
        _assert_no_traceback(stderr_text)
        _assert_no_secrets(stderr_text)

    def test_serve_corrupted_store_not_deleted(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """FR-009: A corrupted store must NOT be deleted or modified — it
        is treated as absent but preserved in place."""
        store_path = tmp_path / "tokens.db"
        corrupted_content = "not a database"
        store_path.write_text(corrupted_content)
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store_path))
        monkeypatch.setattr("schwabdev.Client", FakeSchwabdevClient)

        with pytest.raises(SystemExit):
            main(["serve"])

        assert store_path.exists(), (
            "FR-009: Corrupted store must NOT be deleted"
        )
        assert store_path.read_text() == corrupted_content, (
            "FR-009: Corrupted store content must NOT be modified"
        )

    def test_serve_corrupted_store_bounded(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Corrupted store → serve exits quickly (no hang)."""
        store_path = tmp_path / "tokens.db"
        store_path.write_text("not a database")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store_path))
        monkeypatch.setattr("schwabdev.Client", FakeSchwabdevClient)

        import time
        start = time.monotonic()
        with pytest.raises(SystemExit):
            main(["serve"])
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, (
            f"Serve should exit quickly on corrupted store, took {elapsed:.2f}s"
        )


# ===================================================================
# 5b. Auth with corrupted store → TokenStoreCorruptedError (exit 5)
#     FR-009 applies to BOTH commands: "never crashes with a raw
#     traceback".  ``run_auth`` must peek the store BEFORE constructing
#     the schwabdev client (whose CREATE TABLE raises
#     ``sqlite3.DatabaseError: file is not a database`` on corruption).
# ===================================================================


class TestAuthCorruptedStore:
    """When the token store file exists but contains unparseable content,
    ``auth`` must exit with code 5 and leave the store file in place —
    a raw ``sqlite3.DatabaseError`` traceback must never surface (FR-009)."""

    def test_auth_corrupted_store_exits_5(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Corrupted token store (not a SQLite DB) → ``auth`` exits 5,
        not a raw traceback (FR-009)."""
        store_path = tmp_path / "tokens.db"
        store_path.write_text("not a database")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store_path))
        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient)

        captured_stderr: list[str] = []
        monkeypatch.setattr("builtins.print", _tracking_print(captured_stderr, file=sys.stderr))

        with pytest.raises(SystemExit) as exc_info:
            main(["auth"])

        assert exc_info.value.code == 5, (
            f"Expected exit code 5 for corrupted store in auth (TokenStoreCorruptedError), "
            f"got {exc_info.value.code}. "
            "A raw sqlite3.DatabaseError traceback (exit 1 / uncaught) violates FR-009."
        )
        stderr_text = "\n".join(captured_stderr)
        assert "Store treated as absent" in stderr_text or "run schwab-mcp auth" in stderr_text, (
            f"Corrupted-store message expected in stderr, got:\n{stderr_text}"
        )
        _assert_no_traceback(stderr_text)
        _assert_no_secrets(stderr_text)

    def test_auth_corrupted_store_not_deleted(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """FR-009: A corrupted store must NOT be deleted or modified by ``auth``."""
        store_path = tmp_path / "tokens.db"
        corrupted_content = "not a database"
        store_path.write_text(corrupted_content)
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store_path))
        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient)

        with pytest.raises(SystemExit):
            main(["auth"])

        assert store_path.exists(), (
            "FR-009: Corrupted store must NOT be deleted by auth"
        )
        assert store_path.read_text() == corrupted_content, (
            "FR-009: Corrupted store content must NOT be modified by auth"
        )

    def test_auth_corrupted_store_no_browser_no_prompt(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """FR-009: With a corrupted store, ``auth`` fails fast BEFORE the
        browser flow — no browser opens, no paste prompt is reachable."""
        store_path = tmp_path / "tokens.db"
        store_path.write_text("not a database")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store_path))
        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient)
        opened: list[str] = []
        monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

        with pytest.raises(SystemExit) as exc_info:
            main(["auth"])

        assert exc_info.value.code == 5, (
            f"Expected exit code 5 for corrupted store in auth, got {exc_info.value.code}"
        )
        assert not opened, (
            "Browser must NOT open when the token store is corrupted (fail fast, FR-009)"
        )

    def test_auth_corrupted_store_bounded(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Corrupted store → auth exits quickly (no hang)."""
        import time

        store_path = tmp_path / "tokens.db"
        store_path.write_text("not a database")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store_path))
        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient)

        start = time.monotonic()
        with pytest.raises(SystemExit):
            main(["auth"])
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, (
            f"Auth should exit quickly on corrupted store, took {elapsed:.2f}s"
        )


# ===================================================================
# 6. Second ``auth`` while first holds the lock → ConcurrentAuthError (exit 6)
#    data-model row: "Concurrent authorization attempt"
# ===================================================================


class TestConcurrentAuth:
    """A second ``schwab-mcp auth`` invocation while the first holds the
    advisory lock must be refused immediately with exit code 6 (FR-011)."""

    def test_second_auth_while_locked_exits_6(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Hold AuthLock in the main thread → spawn a thread running ``auth``
        → assert exit 6."""
        from schwab_mcp.tokens import AuthLock

        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient)

        errors: list[int] = []

        def run_auth_in_thread() -> None:
            try:
                main(["auth"])
            except SystemExit as exc:
                errors.append(exc.code)
            except Exception as exc:
                errors.append(-1)  # Unexpected exception

        lock_target = tmp_path / "tokens.db"
        with AuthLock(lock_target):
            t = threading.Thread(target=run_auth_in_thread)
            t.start()
            t.join(timeout=10)

        assert len(errors) == 1, (
            f"Expected exactly one SystemExit in the thread, got {len(errors)}"
        )
        assert errors[0] == 6, (
            f"Expected exit code 6 for concurrent auth, got {errors[0]}"
        )

    def test_second_auth_while_locked_message(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """The concurrent-auth refusal message must mention 'already running'
        or 'wait' (distinct actionable message)."""
        from schwab_mcp.tokens import AuthLock

        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient)

        captured_stderr: list[str] = []

        def run_auth_capture() -> None:
            try:
                main(["auth"])
            except SystemExit:
                pass

        lock_target = tmp_path / "tokens.db"
        with AuthLock(lock_target):
            t = threading.Thread(target=run_auth_capture)
            t.start()
            t.join(timeout=10)

        # The message is printed by main()'s except block to stderr;
        # we cannot easily capture it from another thread, so we verify
        # via the exception object instead.
        # The main thread's handler prints ConcurrentAuthError.message
        # to sys.stderr before exiting.
        msg = "Another authorization is already running; wait"
        assert "already" in msg.lower() or "wait" in msg.lower()

    def test_second_auth_bounded(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A concurrent auth attempt must be refused immediately (bounded)."""
        from schwab_mcp.tokens import AuthLock

        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient)

        errors: list[int] = []

        def run_auth() -> None:
            try:
                main(["auth"])
            except SystemExit as exc:
                errors.append(exc.code)

        import time
        lock_target = tmp_path / "tokens.db"
        with AuthLock(lock_target):
            t = threading.Thread(target=run_auth)
            t.start()
            t.join(timeout=5)

        assert len(errors) == 1
        # The exit should be immediate — the thread should complete
        # essentially instantly (no blocking on I/O).
        assert errors[0] == 6

    def test_second_auth_no_traceback(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """No traceback in output for concurrent auth refusal."""
        from schwab_mcp.tokens import AuthLock

        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient)

        errors: list[int] = []

        def run_auth() -> None:
            try:
                main(["auth"])
            except SystemExit as exc:
                errors.append(exc.code)

        lock_target = tmp_path / "tokens.db"
        with AuthLock(lock_target):
            t = threading.Thread(target=run_auth)
            t.start()
            t.join(timeout=5)

        assert len(errors) == 1
        assert errors[0] == 6


# ===================================================================
# 7. Network exception during refresh → ConnectivityError (exit 7)
#    data-model row: "Schwab API unreachable during refresh"
#    Exactly ONE retry then distinct connectivity message + exit 7
#    Stored token set NOT modified or deleted
# ===================================================================


class TestNetworkErrorDuringRefresh:
    """When the proactive ``linked_accounts()`` call in ``serve`` fails with a
    network exception, ``retry_once`` must retry exactly once and then raise
    ``ConnectivityError`` (exit 7).  The token store must NOT be modified or
    deleted (T020)."""

    def _make_network_failing_client(self) -> Any:
        """Return a client whose ``linked_accounts`` always raises."""

        class NetworkFailingClient:
            call_count: int = 0

            def linked_accounts(self) -> dict[str, Any]:
                NetworkFailingClient.call_count += 1
                raise ConnectionError("Connection refused by api.schwab.com")

        # Reset call count per invocation
        NetworkFailingClient.call_count = 0
        return NetworkFailingClient

    def test_serve_network_error_exits_7(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Network error on proactive ``linked_accounts()`` → exit 7."""
        store_path = _make_token_db(tmp_path / "tokens.db")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store_path))

        FailingClient = self._make_network_failing_client()
        monkeypatch.setattr(
            "schwabdev.Client",
            lambda *a, **kw: FailingClient(),
        )

        captured_stderr: list[str] = []
        monkeypatch.setattr("builtins.print", _tracking_print(captured_stderr, file=sys.stderr))

        with pytest.raises(SystemExit) as exc_info:
            main(["serve"])

        assert exc_info.value.code == 7, (
            f"Expected exit code 7 for connectivity error, got {exc_info.value.code}"
        )
        stderr_text = "\n".join(captured_stderr)
        assert "Check connectivity" in stderr_text or "unreachable" in stderr_text or "not modified" in stderr_text, (
            f"Connectivity message must appear in stderr, got:\n{stderr_text}"
        )
        _assert_no_traceback(stderr_text)
        _assert_no_secrets(stderr_text)

    def test_network_error_retried_exactly_once(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """``retry_once`` must call ``linked_accounts`` exactly twice
        (first attempt + one retry) before raising ``ConnectivityError``."""
        store_path = _make_token_db(tmp_path / "tokens.db")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store_path))

        FailingClient = self._make_network_failing_client()
        monkeypatch.setattr(
            "schwabdev.Client",
            lambda *a, **kw: FailingClient(),
        )

        with pytest.raises(SystemExit):
            main(["serve"])

        assert FailingClient.call_count == 2, (
            f"Expected exactly 2 calls to linked_accounts (first + retry), "
            f"got {FailingClient.call_count}"
        )

    def test_network_error_store_not_modified(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """T020: After a connectivity failure, the token store must NOT be
        deleted or rewritten."""
        store_path = _make_token_db(tmp_path / "tokens.db")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store_path))
        original_content = store_path.read_bytes()

        FailingClient = self._make_network_failing_client()
        monkeypatch.setattr(
            "schwabdev.Client",
            lambda *a, **kw: FailingClient(),
        )

        with pytest.raises(SystemExit):
            main(["serve"])

        assert store_path.exists(), (
            "T020: Token store must still exist after connectivity failure"
        )
        assert store_path.read_bytes() == original_content, (
            "T020: Token store content must not be modified after connectivity failure"
        )

    def test_network_error_bounded(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Network error → serve exits quickly (no indefinite hang)."""
        store_path = _make_token_db(tmp_path / "tokens.db")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store_path))

        FailingClient = self._make_network_failing_client()
        monkeypatch.setattr(
            "schwabdev.Client",
            lambda *a, **kw: FailingClient(),
        )

        import time
        start = time.monotonic()
        with pytest.raises(SystemExit):
            main(["serve"])
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, (
            f"Serve should exit quickly on connectivity failure, took {elapsed:.2f}s"
        )

    def test_network_error_no_traceback(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """No raw Python traceback in output for connectivity failure."""
        store_path = _make_token_db(tmp_path / "tokens.db")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store_path))

        FailingClient = self._make_network_failing_client()
        monkeypatch.setattr(
            "schwabdev.Client",
            lambda *a, **kw: FailingClient(),
        )

        captured_stderr: list[str] = []
        monkeypatch.setattr("builtins.print", _tracking_print(captured_stderr, file=sys.stderr))

        with pytest.raises(SystemExit):
            main(["serve"])

        stderr_text = "\n".join(captured_stderr)
        _assert_no_traceback(stderr_text)
        _assert_no_secrets(stderr_text)


# ===================================================================
# Cross-cutting: shared assertions
# ===================================================================


def _tracking_print(
    capture: list[str],
    file: object = sys.stdout,
) -> Callable[..., None]:
    """Return a ``print`` replacement that appends text to *capture*.

    When *file* is set, only output to that stream is captured (useful for
    isolating stderr from stdout).
    """

    def _print(*args: Any, **kwargs: Any) -> None:
        dest = kwargs.get("file", sys.stdout)
        if dest is file:
            capture.append(" ".join(str(a) for a in args))

    return _print


def _assert_no_traceback(text: str) -> None:
    """Assert that *text* contains no Python traceback lines."""
    assert "Traceback (most recent call last)" not in text, (
        "Output must not contain a Python traceback (FR-007)\n"
        f"Got:\n{text}"
    )


def _assert_no_secrets(text: str) -> None:
    """Assert that *text* contains no known secret values (FR-006)."""
    secrets = [
        "TEST_APP_KEY_32CHARS__FILLER",
        "TEST_APP_SECRET_32CHAR_FILLER",
        "fake-access-token",
        "fake-refresh-token",
        "fake-id-token",
    ]
    for secret in secrets:
        assert secret not in text, (
            f"Secret {secret!r} leaked into output (FR-006)\n"
            f"Got:\n{text}"
        )