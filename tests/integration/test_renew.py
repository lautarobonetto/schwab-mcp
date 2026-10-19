"""FAILING integration tests for ``schwab-mcp renew`` (US2 / T012).

These tests verify the ``renew`` subcommand per contracts/cli.md (feature
002-automated-token-renewal).  The ``renew`` subcommand does NOT exist in
the current ``cli.py`` implementation, so every test is expected to FAIL
(exit 1 via fallthrough to ``parser.print_help()``) during this TDD RED
phase.

Once the subcommand is wired, these tests assert:

- The documented exit code for each outcome (0, 2, 3, 6, 7) per
  contracts/cli.md.
- Exactly one JSON line on stdout, ≤ 300 bytes (SC-005).
- No network activity when the token is still valid (FR-002 AC2).
- No client construction when config is missing (FR-008) or store is
  absent/corrupted.

References
----------
- specs/002-automated-token-renewal/contracts/cli.md : Exit code definitions
  for ``renew``.
- src/schwab_mcp/renewal.py : ``renew()`` orchestration function.
- data-model.md §1 : Renewal outcome types and vocabulary.
- FR-002 : Non-interactive, one-shot renewal.
- FR-003 : Outcome classification.
- FR-004 : No secrets in JSON output.
- FR-005 : Concurrent exclusion for renewal.
- FR-006 : Retry on transient failure.
- FR-008 : Fail-fast on missing config.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable
from unittest import mock

import pytest

from schwab_mcp.cli import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token_db(
    path: Path,
    *,
    access_issued: float | None = None,
    expires_in: int = 1800,
    refresh_issued: float | None = None,
) -> Path:
    """Create a valid schwabdev SQLite token store at *path*.

    Uses **REAL** timestamps (Unix epoch seconds) for the issued-at columns
    so that ``read_store_lifetime()`` can compute remaining lifetimes
    correctly — consistent with ``test_renewal_flow.py``.

    Parameters
    ----------
    path
        Where to create the store file.
    access_issued
        Unix timestamp for ``access_token_issued``.  Defaults to ``now``.
    expires_in
        ``expires_in`` column value (seconds of access token validity).
    refresh_issued
        Unix timestamp for ``refresh_token_issued``.  Defaults to ``now``.
    """
    now = time.time()
    if access_issued is None:
        access_issued = now
    if refresh_issued is None:
        refresh_issued = now

    con = sqlite3.connect(str(path))
    try:
        con.execute(
            "CREATE TABLE schwabdev ("
            "  access_token TEXT,"
            "  refresh_token TEXT,"
            "  id_token TEXT,"
            "  access_token_issued REAL,"
            "  refresh_token_issued REAL,"
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
                access_issued,
                refresh_issued,
                expires_in,
                "Bearer",
                "readonly",
            ),
        )
        con.commit()
    finally:
        con.close()
    return path


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
        f"Output must not contain a Python traceback\nGot:\n{text}"
    )


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
# Test class: schwab-mcp renew
# ===================================================================


class TestRenewCommand:
    """``schwab-mcp renew`` exit codes and stdout JSON contract.

    The ``renew`` subcommand does NOT exist in the current ``cli.py``
    implementation, so all tests are expected to FAIL with exit code 1
    (fallthrough to ``parser.print_help()``) during this TDD RED phase.
    """

    def test_renewed_exit_0(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Expired access token successfully renewed → exit 0, stdout has
        exactly one JSON line with ``outcome: "renewed"`` (≤ 300 bytes)."""
        # Create a token store with expired access (short expires_in,
        # issued long ago).
        store = _make_token_db(
            tmp_path / "tokens.db",
            access_issued=time.time() - 7200,  # 2 hours ago
            expires_in=30,  # 30-second validity — long expired
        )
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store))

        # Capture stdout
        captured_stdout: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stdout, file=sys.stdout)
        )

        # Mock the client so update_tokens returns True (successful renewal)
        client_mock = mock.MagicMock()
        client_mock.update_tokens.return_value = True
        client_mock.linked_accounts.return_value = {"accounts": []}

        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client",
            lambda *a, **kw: client_mock,
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["renew"])

        assert exc_info.value.code == 0, (
            f"Expected exit code 0 for successful renewal, "
            f"got {exc_info.value.code}. "
            "Note: renew subcommand not yet wired — this FAIL is expected "
            "TDD red phase."
        )
        assert len(captured_stdout) == 1, (
            f"Expected exactly one line on stdout, got {len(captured_stdout)}"
        )
        payload = json.loads(captured_stdout[0])
        assert payload["outcome"] == "renewed", (
            f"Expected outcome 'renewed', got {payload['outcome']!r}"
        )
        assert payload["retryable"] is False, (
            "A successful renewal must have retryable=False"
        )
        assert payload["detail"] == "access_renewed", (
            f"Expected detail 'access_renewed', got {payload['detail']!r}"
        )
        # Verify ≤ 300 bytes (contract SC-005)
        byte_len = len(captured_stdout[0].encode("utf-8"))
        assert byte_len <= 300, (
            f"JSON payload must not exceed 300 bytes, got {byte_len}"
        )

    def test_not_needed_exit_0(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Token still valid above margin → exit 0, ``outcome: "not_needed"``,
        no provider call made (FR-002 AC2)."""
        # Create a store with fresh access (just issued, long validity).
        store = _make_token_db(
            tmp_path / "tokens.db",
            access_issued=time.time(),
            expires_in=3600,  # 1 hour validity — well above 61s margin
        )
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store))

        captured_stdout: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stdout, file=sys.stdout)
        )

        # Track whether update_tokens is ever called
        client_mock = mock.MagicMock()
        client_mock.update_tokens.return_value = True
        client_mock.linked_accounts.return_value = {"accounts": []}

        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client",
            lambda *a, **kw: client_mock,
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["renew"])

        assert exc_info.value.code == 0, (
            f"Expected exit code 0 for 'not_needed', got {exc_info.value.code}. "
            "Note: renew subcommand not yet wired — this FAIL is expected "
            "TDD red phase."
        )
        assert client_mock.update_tokens.call_count == 0, (
            "update_tokens must NOT be called when the token is still valid "
            "(FR-002 AC2)"
        )
        assert client_mock.linked_accounts.call_count == 0, (
            "No provider call of any kind should happen when not_needed"
        )
        assert len(captured_stdout) == 1, (
            f"Expected exactly one line on stdout, got {len(captured_stdout)}"
        )
        payload = json.loads(captured_stdout[0])
        assert payload["outcome"] == "not_needed", (
            f"Expected outcome 'not_needed', got {payload['outcome']!r}"
        )
        assert payload["detail"] == "still_valid", (
            f"Expected detail 'still_valid', got {payload['detail']!r}"
        )
        assert payload["retryable"] is False
        byte_len = len(captured_stdout[0].encode("utf-8"))
        assert byte_len <= 300, (
            f"JSON payload must not exceed 300 bytes, got {byte_len}"
        )

    def test_transient_failure_exit_7(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``update_tokens()`` raises ``ConnectionError`` → exit 7, stdout
        JSON has ``retryable: true``."""
        store = _make_token_db(
            tmp_path / "tokens.db",
            access_issued=time.time() - 7200,
            expires_in=30,
        )
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store))

        captured_stdout: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stdout, file=sys.stdout)
        )

        # Mock client: update_tokens always raises ConnectionError
        client_mock = mock.MagicMock()
        client_mock.update_tokens.side_effect = ConnectionError(
            "Connection refused by api.schwab.com"
        )

        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client",
            lambda *a, **kw: client_mock,
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["renew"])

        assert exc_info.value.code == 7, (
            f"Expected exit code 7 for transient failure, got {exc_info.value.code}. "
            "Note: renew subcommand not yet wired — this FAIL is expected "
            "TDD red phase."
        )
        assert len(captured_stdout) == 1, (
            f"Expected exactly one line on stdout, got {len(captured_stdout)}"
        )
        payload = json.loads(captured_stdout[0])
        assert payload["outcome"] == "transient_failure", (
            f"Expected outcome 'transient_failure', got {payload['outcome']!r}"
        )
        assert payload["retryable"] is True, (
            "Transient failure must have retryable=True"
        )
        assert payload["detail"] == "provider_unreachable", (
            f"Expected detail 'provider_unreachable', got {payload['detail']!r}"
        )
        byte_len = len(captured_stdout[0].encode("utf-8"))
        assert byte_len <= 300, (
            f"JSON payload must not exceed 300 bytes, got {byte_len}"
        )

    def test_missing_config_exit_2(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Missing env vars → exit 2 BEFORE any network/client activity
        (FR-008)."""
        monkeypatch.delenv("SCHWAB_APP_KEY", raising=False)
        monkeypatch.delenv("SCHWAB_APP_SECRET", raising=False)

        captured_stderr: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stderr, file=sys.stderr)
        )

        # Fail if any Client is constructed (shouldn't happen when config
        # is missing).
        def fail_if_called(*a: Any, **kw: Any) -> object:
            raise RuntimeError("No Client should be constructed when config is missing")

        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", fail_if_called
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["renew"])

        assert exc_info.value.code == 2, (
            f"Expected exit code 2 for missing config, got {exc_info.value.code}. "
            "Note: renew subcommand not yet wired — this FAIL is expected "
            "TDD red phase."
        )
        stderr_text = "\n".join(captured_stderr)
        assert "SCHWAB_APP_KEY" in stderr_text or "SCHWAB_APP_SECRET" in stderr_text, (
            f"Missing-config message should appear in stderr, got:\n{stderr_text}"
        )
        _assert_no_traceback(stderr_text)

    def test_store_absent_exit_3(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No token store at configured path → exit 3 with detail
        ``store_absent``."""
        # Do NOT create any store — the env defaults to a non-existent path.
        captured_stdout: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stdout, file=sys.stdout)
        )

        # Fail if any Client is constructed (shouldn't happen when the
        # store is absent).
        def fail_if_called(*a: Any, **kw: Any) -> object:
            raise RuntimeError(
                "No Client should be constructed when the store is absent"
            )

        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", fail_if_called
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["renew"])

        assert exc_info.value.code == 3, (
            f"Expected exit code 3 for absent store, got {exc_info.value.code}. "
            "Note: renew subcommand not yet wired — this FAIL is expected "
            "TDD red phase."
        )
        assert len(captured_stdout) == 1, (
            f"Expected exactly one line on stdout, got {len(captured_stdout)}"
        )
        payload = json.loads(captured_stdout[0])
        assert payload["outcome"] == "reauth_required", (
            f"Expected outcome 'reauth_required', got {payload['outcome']!r}"
        )
        assert payload["detail"] == "store_absent", (
            f"Expected detail 'store_absent', got {payload['detail']!r}"
        )
        assert payload["retryable"] is False
        byte_len = len(captured_stdout[0].encode("utf-8"))
        assert byte_len <= 300, (
            f"JSON payload must not exceed 300 bytes, got {byte_len}"
        )

    def test_store_corrupted_exit_3(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Corrupted token store (not a SQLite DB) → exit 3 with detail
        ``store_corrupted``."""
        store = tmp_path / "tokens.db"
        store.write_text("not a database")

        captured_stdout: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stdout, file=sys.stdout)
        )

        # Fail if any Client is constructed (shouldn't happen when the
        # store is corrupted).
        def fail_if_called(*a: Any, **kw: Any) -> object:
            raise RuntimeError(
                "No Client should be constructed when the store is corrupted"
            )

        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", fail_if_called
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["renew"])

        assert exc_info.value.code == 3, (
            f"Expected exit code 3 for corrupted store, got {exc_info.value.code}. "
            "Note: renew subcommand not yet wired — this FAIL is expected "
            "TDD red phase."
        )
        assert store.exists(), (
            "FR-009: Corrupted store must NOT be deleted"
        )
        assert len(captured_stdout) == 1, (
            f"Expected exactly one line on stdout, got {len(captured_stdout)}"
        )
        payload = json.loads(captured_stdout[0])
        assert payload["outcome"] == "reauth_required", (
            f"Expected outcome 'reauth_required', got {payload['outcome']!r}"
        )
        assert payload["detail"] == "store_corrupted", (
            f"Expected detail 'store_corrupted', got {payload['detail']!r}"
        )
        assert payload["retryable"] is False
        byte_len = len(captured_stdout[0].encode("utf-8"))
        assert byte_len <= 300, (
            f"JSON payload must not exceed 300 bytes, got {byte_len}"
        )

    def test_concurrent_renewal_exit_6(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Another renewal/authorization already in progress → exit 6
        (FR-005)."""
        from schwab_mcp.tokens import AuthLock

        store = _make_token_db(
            tmp_path / "tokens.db",
            access_issued=time.time() - 7200,
            expires_in=30,
        )
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store))

        captured_stdout: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stdout, file=sys.stdout)
        )

        errors: list[int] = []

        def run_renew_in_thread() -> None:
            try:
                main(["renew"])
            except SystemExit as exc:
                errors.append(exc.code)
            except Exception:
                errors.append(-1)  # Unexpected exception

        # Hold the advisory auth lock, then try to run renew in a thread.
        # This mirrors the concurrent auth test pattern from
        # test_failures.py (TestConcurrentAuth).
        lock_target = tmp_path / "tokens.db"
        with AuthLock(lock_target):
            t = threading.Thread(target=run_renew_in_thread)
            t.start()
            t.join(timeout=10)

        assert len(errors) == 1, (
            f"Expected exactly one SystemExit in the thread, got {len(errors)}"
        )
        assert errors[0] == 6, (
            f"Expected exit code 6 for concurrent renewal, got {errors[0]}. "
            "Note: renew subcommand not yet wired — this FAIL is expected "
            "TDD red phase."
        )


# ===================================================================
# Test class: re-authorization-required consistency (US3 / T014)
# ===================================================================


class TestReauthRequired:
    """``schwab-mcp renew`` consistency when the refresh credential is
    permanently unusable (US3 / T014).

    When ``ReauthorizationRequiredError`` is raised by the provider or by
    the guard hook, ``renew`` must:

    - Exit 3 with a stable outcome classification.
    - Never enter an unbounded retry loop (FR-007).
    - Return to normal after a successful re-authorization.
    """

    def test_renew_exit_3_reauth_required(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``update_tokens()`` raises ``ReauthorizationRequiredError`` →
        exit 3, stdout has ``outcome: "reauth_required"`` and
        ``detail: "reauth_needed"``."""
        from schwab_mcp.errors import ReauthorizationRequiredError

        store = _make_token_db(
            tmp_path / "tokens.db",
            access_issued=time.time() - 7200,
            expires_in=30,
        )
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store))

        captured_stdout: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stdout, file=sys.stdout)
        )

        client_mock = mock.MagicMock()
        client_mock.update_tokens.side_effect = ReauthorizationRequiredError()

        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client",
            lambda *a, **kw: client_mock,
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["renew"])

        assert exc_info.value.code == 3, (
            f"Expected exit code 3 for reauth_required, "
            f"got {exc_info.value.code}."
        )
        assert len(captured_stdout) == 1, (
            f"Expected exactly one line on stdout, got {len(captured_stdout)}"
        )
        payload = json.loads(captured_stdout[0])
        assert payload["outcome"] == "reauth_required", (
            f"Expected outcome 'reauth_required', got {payload['outcome']!r}"
        )
        assert payload["detail"] == "reauth_needed", (
            f"Expected detail 'reauth_needed', got {payload['detail']!r}"
        )
        assert payload["retryable"] is False
        byte_len = len(captured_stdout[0].encode("utf-8"))
        assert byte_len <= 300, (
            f"JSON payload must not exceed 300 bytes, got {byte_len}"
        )

    def test_repeated_reauth_bounded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Repeated ``renew`` with ``ReauthorizationRequiredError`` → both
        exit 3 with bounded ``update_tokens`` calls (no unbounded retry
        loop, FR-007)."""
        from schwab_mcp.errors import ReauthorizationRequiredError

        store = _make_token_db(
            tmp_path / "tokens.db",
            access_issued=time.time() - 7200,
            expires_in=30,
        )
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store))

        captured_stdout: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stdout, file=sys.stdout)
        )

        client_mock = mock.MagicMock()
        client_mock.update_tokens.side_effect = ReauthorizationRequiredError()

        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client",
            lambda *a, **kw: client_mock,
        )

        # First invocation → SystemExit(3)
        with pytest.raises(SystemExit) as exc_info:
            main(["renew"])

        assert exc_info.value.code == 3, (
            f"Expected exit code 3 for first reauth, "
            f"got {exc_info.value.code}."
        )

        # Second invocation → SystemExit(3) again
        with pytest.raises(SystemExit) as exc_info2:
            main(["renew"])

        assert exc_info2.value.code == 3, (
            f"Expected exit code 3 for second reauth, "
            f"got {exc_info2.value.code}."
        )

        # Verify bounded calls: ReauthorizationRequiredError short-circuits
        # immediately (no retry), so each invocation calls update_tokens
        # exactly once.  Assert at most (1 + RETRIES) * 2 = 6 calls to
        # prevent any unbounded retry regression.
        max_expected = (1 + 2) * 2  # 1 initial + 2 retries per invocation
        assert client_mock.update_tokens.call_count <= max_expected, (
            f"update_tokens called {client_mock.update_tokens.call_count} times, "
            f"expected at most {max_expected} (bounded, no unbounded loop)"
        )

    def test_reauth_resolved_after_reauthorization(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """After ``renew`` exits 3 due to ``ReauthorizationRequiredError``,
        a stubbed successful re-authorization allows the next ``renew`` to
        exit 0."""
        from schwab_mcp.errors import ReauthorizationRequiredError

        store_path = tmp_path / "tokens.db"

        # First: expired token store
        _make_token_db(
            store_path,
            access_issued=time.time() - 7200,
            expires_in=30,
        )
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store_path))

        captured_stdout: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stdout, file=sys.stdout)
        )

        client_mock = mock.MagicMock()
        # First invocation raises; subsequent invocations succeed.
        client_mock.update_tokens.side_effect = [
            ReauthorizationRequiredError(),
            True,
            True,
        ]

        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client",
            lambda *a, **kw: client_mock,
        )

        # --- First run: provider rejects the refresh credential ---
        with pytest.raises(SystemExit) as exc_info:
            main(["renew"])

        assert exc_info.value.code == 3, (
            f"Expected exit code 3 for reauth_required, "
            f"got {exc_info.value.code}."
        )
        payload = json.loads(captured_stdout[0])
        assert payload["outcome"] == "reauth_required"

        # --- Simulate successful re-authorization ---
        # Remove the old store and create fresh tokens.
        store_path.unlink(missing_ok=True)
        _make_token_db(
            store_path,
            access_issued=time.time() - 7200,
            expires_in=30,
        )

        # Clear captured output before the second run.
        captured_stdout.clear()

        # --- Second run: should succeed ---
        with pytest.raises(SystemExit) as exc_info2:
            main(["renew"])

        assert exc_info2.value.code == 0, (
            f"Expected exit code 0 after successful re-auth, "
            f"got {exc_info2.value.code}."
        )
        assert len(captured_stdout) == 1, (
            f"Expected exactly one line on stdout, got {len(captured_stdout)}"
        )
        payload2 = json.loads(captured_stdout[0])
        assert payload2["outcome"] in ("renewed", "not_needed"), (
            f"Expected outcome 'renewed' or 'not_needed' after re-auth, "
            f"got {payload2['outcome']!r}"
        )
        assert payload2["retryable"] is False
        byte_len = len(captured_stdout[0].encode("utf-8"))
        assert byte_len <= 300, (
            f"JSON payload must not exceed 300 bytes, got {byte_len}"
        )