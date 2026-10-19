"""FAILING integration tests for ``schwab-mcp auth-status`` (US3 / T015).

These tests verify the ``auth-status`` subcommand per contracts/cli.md (feature
002-automated-token-renewal).  The ``auth-status`` subcommand does NOT exist in
the current ``cli.py`` implementation, so every test is expected to FAIL
(exit 1 via fallthrough to ``parser.print_help()``) during this TDD RED
phase.

Once the subcommand is wired, these tests assert:

- The documented exit code for each outcome (0, 2, 3) per contracts/cli.md.
- Exactly one JSON line on stdout, ≤ 300 bytes (SC-005).
- No network activity ever (FR-008 — local read only, ≤ 2 s).
- No client construction: ``auth-status`` is strictly read-only.
- ``access_expires_in_seconds`` and ``refresh_expires_in_seconds`` are
  present in ``valid`` responses.

References
----------
- specs/002-automated-token-renewal/contracts/cli.md : Exit code definitions
  for ``auth-status``.
- src/schwab_mcp/renewal.py : ``AuthHealth`` result type and
  ``read_store_lifetime()``.
- data-model.md §2 : AuthHealth fields and vocabulary.
- FR-008 : Non-interactive, one-shot health query (local read only,
  ≤ 2 s, never triggers a renewal).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

import pytest

from schwab_mcp.cli import main


# ---------------------------------------------------------------------------
# Helpers  (mirrors test_renew.py)
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
    correctly.
    """
    import sqlite3

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
    """Return a ``print`` replacement that appends text to *capture*."""

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
    """Set up a clean environment with valid but fake credentials."""
    monkeypatch.setenv("SCHWAB_APP_KEY", "TEST_APP_KEY_32CHARS__FILLER")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "TEST_APP_SECRET_32CHAR_FILLER")
    monkeypatch.setenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1")
    token_db = str(tmp_path / "tokens.db")
    monkeypatch.setenv("SCHWAB_TOKEN_DB", token_db)
    tmp_path.mkdir(parents=True, exist_ok=True)


# ===================================================================
# Test class: schwab-mcp auth-status
# ===================================================================


class TestAuthStatusCommand:
    """``schwab-mcp auth-status`` exit codes and stdout JSON contract."""

    def test_valid_exit_0(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Valid token store → exit 0, stdout has ``state: "valid"`` with
        expiry fields as positive integers (no Client constructed)."""
        store = _make_token_db(
            tmp_path / "tokens.db",
            access_issued=time.time(),
            expires_in=3600,
        )
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store))

        captured_stdout: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stdout, file=sys.stdout)
        )

        def fail_if_called(*a: Any, **kw: Any) -> object:
            raise RuntimeError("No Client should be constructed during auth-status")

        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", fail_if_called)

        with pytest.raises(SystemExit) as exc_info:
            main(["auth-status"])

        assert exc_info.value.code == 0, (
            f"Expected exit code 0, got {exc_info.value.code}"
        )
        assert len(captured_stdout) == 1
        payload = json.loads(captured_stdout[0])
        assert payload["state"] == "valid"
        assert payload.get("access_expires_in_seconds", -1) >= 0
        assert payload.get("refresh_expires_in_seconds", -1) >= 0
        byte_len = len(captured_stdout[0].encode("utf-8"))
        assert byte_len <= 300, f"JSON payload must not exceed 300 bytes, got {byte_len}"

    def test_store_absent_exit_3(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No token store → exit 3, state ``reauth_required``, detail ``store_absent``."""
        captured_stdout: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stdout, file=sys.stdout)
        )

        def fail_if_called(*a: Any, **kw: Any) -> object:
            raise RuntimeError("No Client should be constructed when the store is absent")

        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", fail_if_called)

        with pytest.raises(SystemExit) as exc_info:
            main(["auth-status"])

        assert exc_info.value.code == 3, (
            f"Expected exit code 3 for absent store, got {exc_info.value.code}"
        )
        assert len(captured_stdout) == 1
        payload = json.loads(captured_stdout[0])
        assert payload["state"] == "reauth_required"
        assert payload.get("access_expires_in_seconds") is None
        assert payload.get("refresh_expires_in_seconds") is None
        byte_len = len(captured_stdout[0].encode("utf-8"))
        assert byte_len <= 300, f"JSON payload must not exceed 300 bytes, got {byte_len}"

    def test_store_corrupted_exit_3(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Corrupted store → exit 3, state ``reauth_required``, store NOT deleted."""
        store = tmp_path / "tokens.db"
        store.write_text("not a database")

        captured_stdout: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stdout, file=sys.stdout)
        )

        def fail_if_called(*a: Any, **kw: Any) -> object:
            raise RuntimeError("No Client should be constructed when the store is corrupted")

        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", fail_if_called)

        with pytest.raises(SystemExit) as exc_info:
            main(["auth-status"])

        assert exc_info.value.code == 3, (
            f"Expected exit code 3 for corrupted store, got {exc_info.value.code}"
        )
        assert store.exists(), "FR-009: Corrupted store must NOT be deleted"
        assert len(captured_stdout) == 1
        payload = json.loads(captured_stdout[0])
        assert payload["state"] == "reauth_required"
        assert payload.get("access_expires_in_seconds") is None
        assert payload.get("refresh_expires_in_seconds") is None
        byte_len = len(captured_stdout[0].encode("utf-8"))
        assert byte_len <= 300, f"JSON payload must not exceed 300 bytes, got {byte_len}"

    def test_missing_config_exit_2(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Missing env vars → exit 2 BEFORE any store activity."""
        monkeypatch.delenv("SCHWAB_APP_KEY", raising=False)
        monkeypatch.delenv("SCHWAB_APP_SECRET", raising=False)

        captured_stderr: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stderr, file=sys.stderr)
        )

        def fail_if_called(*a: Any, **kw: Any) -> object:
            raise RuntimeError("No Client should be constructed when config is missing")

        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", fail_if_called)

        with pytest.raises(SystemExit) as exc_info:
            main(["auth-status"])

        assert exc_info.value.code == 2, (
            f"Expected exit code 2 for missing config, got {exc_info.value.code}"
        )
        stderr_text = "\n".join(captured_stderr)
        assert "SCHWAB_APP_KEY" in stderr_text or "SCHWAB_APP_SECRET" in stderr_text
        _assert_no_traceback(stderr_text)

    def test_no_network_call_made(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Valid store → exit 0, no Client constructed (read-only)."""
        store = _make_token_db(
            tmp_path / "tokens.db",
            access_issued=time.time(),
            expires_in=3600,
        )
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(store))

        captured_stdout: list[str] = []
        monkeypatch.setattr(
            "builtins.print", _tracking_print(captured_stdout, file=sys.stdout)
        )

        def fail_if_called(*a: Any, **kw: Any) -> object:
            raise RuntimeError("schwabdev.Client must NOT be constructed during auth-status")

        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", fail_if_called)

        with pytest.raises(SystemExit) as exc_info:
            main(["auth-status"])

        assert exc_info.value.code == 0, (
            f"Expected exit code 0, got {exc_info.value.code}"
        )
        assert len(captured_stdout) == 1
        payload = json.loads(captured_stdout[0])
        assert payload["state"] == "valid"
        byte_len = len(captured_stdout[0].encode("utf-8"))
        assert byte_len <= 300, f"JSON payload must not exceed 300 bytes, got {byte_len}"