"""Failing unit tests for token-store peek, permission enforcement, and advisory auth lock.

These are TDD red-phase tests: the source module (schwab_mcp.tokens) does
not exist yet, so every test will fail with ModuleNotFoundError / ImportError.
Once implemented, all tests should pass.

References
----------
- FR-003: enforce_permissions sets 0o600 on file, 0o700 on directory.
- FR-009: corrupted store → treated as absent (not a crash).
- FR-011: concurrent auth attempts → ConcurrentAuthError.
"""

from __future__ import annotations

import os
import sqlite3
import stat
import threading
from pathlib import Path

import pytest

from schwab_mcp.errors import ConcurrentAuthError
from schwab_mcp.tokens import AuthLock, enforce_permissions, peek_store


# ---------------------------------------------------------------------------
# peek_store
# ---------------------------------------------------------------------------


class TestPeekStore:
    """peek_store(path) → absent-marker (False-ish) vs present-marker (True-ish)."""

    def test_absent_for_missing_file(self, tmp_path: Path) -> None:
        """Non-existent path yields absent-marker, never an exception."""
        nonexistent = tmp_path / "does-not-exist.db"
        result = peek_store(nonexistent)
        assert not result, f"Expected absent-marker, got {result!r}"

    def test_absent_for_corrupted_content(self, tmp_path: Path) -> None:
        """Corrupted/unparseable content (not a SQLite DB) → absent-marker, not crash.

        FR-009: corrupted store must be treated as absent.
        """
        path = tmp_path / "corrupted.db"
        path.write_bytes(b"not a database")
        result = peek_store(path)
        assert not result, f"Expected absent-marker for corrupted store, got {result!r}"

    def test_present_for_valid_sqlite_with_schwabdev_row(self, tmp_path: Path) -> None:
        """A SQLite file containing a single-row schwabdev table → present-marker."""
        path = tmp_path / "valid.db"
        con = sqlite3.connect(str(path))
        try:
            con.execute(
                "CREATE TABLE schwabdev (access_token TEXT, refresh_token TEXT)"
            )
            con.execute(
                "INSERT INTO schwabdev (access_token, refresh_token) VALUES (?, ?)",
                ("dummy_access", "dummy_refresh"),
            )
            con.commit()
        finally:
            con.close()

        result = peek_store(path)
        assert result, f"Expected present-marker for valid store, got {result!r}"


# ---------------------------------------------------------------------------
# enforce_permissions
# ---------------------------------------------------------------------------


class TestEnforcePermissions:
    """enforce_permissions(path) sets restrictive owner-only permissions.

    FR-003: file 0o600, directory 0o700.
    """

    def test_file_permissions_0600(self, tmp_path: Path) -> None:
        """File mode is set to 0o600 (owner read/write only)."""
        path = tmp_path / "tokens.db"
        path.touch(mode=0o777)
        enforce_permissions(path)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_directory_permissions_0700(self, tmp_path: Path) -> None:
        """Parent directory mode is set to 0o700 (owner rwx only)."""
        path = tmp_path / "tokens.db"
        path.touch(mode=0o644)
        tmp_path.chmod(0o755)
        enforce_permissions(path)
        dir_mode = stat.S_IMODE(os.stat(tmp_path).st_mode)
        assert dir_mode == 0o700, f"Expected 0o700, got {oct(dir_mode)}"

    def test_permissions_idempotent(self, tmp_path: Path) -> None:
        """Calling enforce_permissions twice does not raise or toggle modes."""
        path = tmp_path / "tokens.db"
        path.touch()
        enforce_permissions(path)
        file_mode_1 = stat.S_IMODE(os.stat(path).st_mode)
        dir_mode_1 = stat.S_IMODE(os.stat(tmp_path).st_mode)

        enforce_permissions(path)
        file_mode_2 = stat.S_IMODE(os.stat(path).st_mode)
        dir_mode_2 = stat.S_IMODE(os.stat(tmp_path).st_mode)

        assert file_mode_1 == file_mode_2 == 0o600
        assert dir_mode_1 == dir_mode_2 == 0o700


# ---------------------------------------------------------------------------
# AuthLock — advisory concurrent-auth guard
# ---------------------------------------------------------------------------


class TestAuthLock:
    """AuthLock(path) serialises concurrent authorization attempts.

    FR-011: a second concurrent attempt must be refused with ConcurrentAuthError.
    """

    def test_second_concurrent_acquire_raises(self, tmp_path: Path) -> None:
        """Two AuthLock instances on the same path in the same process:
        the second non-blocking acquire raises ConcurrentAuthError.
        """
        lock_path = tmp_path / "auth.lock"
        errors: list[Exception] = []

        def acquire_second() -> None:
            try:
                with AuthLock(lock_path):
                    pass
            except ConcurrentAuthError as exc:
                errors.append(exc)

        with AuthLock(lock_path) as first_lock:
            # While the first lock is held, spawn a thread that tries to
            # acquire the same lock (non-blocking).
            t = threading.Thread(target=acquire_second)
            t.start()
            t.join()

        assert len(errors) == 1, (
            f"Expected exactly one ConcurrentAuthError, got {len(errors)}"
        )
        assert isinstance(errors[0], ConcurrentAuthError)

    def test_held_lock_does_not_corrupt_token_db(self, tmp_path: Path) -> None:
        """A held AuthLock does not modify or corrupt a valid token database.

        FR-011: the lock itself must be side-effect free on the token store.
        """
        db_path = tmp_path / "tokens.db"
        con = sqlite3.connect(str(db_path))
        try:
            con.execute(
                "CREATE TABLE schwabdev (access_token TEXT, refresh_token TEXT)"
            )
            con.execute(
                "INSERT INTO schwabdev (access_token, refresh_token) VALUES (?, ?)",
                ("original_access", "original_refresh"),
            )
            con.commit()
        finally:
            con.close()

        checksum_before = os.stat(db_path).st_mtime_ns

        with AuthLock(db_path):
            # While holding the lock, verify the DB file is untouched.
            checksum_during = os.stat(db_path).st_mtime_ns
            assert checksum_during == checksum_before, (
                "Lock acquisition modified the token DB mtime"
            )
            con2 = sqlite3.connect(str(db_path))
            try:
                row = con2.execute("SELECT * FROM schwabdev").fetchone()
            finally:
                con2.close()
            assert row is not None
            assert row[0] == "original_access"
            assert row[1] == "original_refresh"

        # After releasing the lock, the DB must still be intact.
        con3 = sqlite3.connect(str(db_path))
        try:
            row = con3.execute("SELECT * FROM schwabdev").fetchone()
        finally:
            con3.close()
        assert row is not None
        assert row[0] == "original_access"
        assert row[1] == "original_refresh"

    def test_lock_releases_after_context(self, tmp_path: Path) -> None:
        """After the first lock context exits, a second acquire succeeds."""
        lock_path = tmp_path / "auth.lock"
        with AuthLock(lock_path):
            pass
        # Second acquire must succeed (no ConcurrentAuthError).
        with AuthLock(lock_path):
            pass

    def test_lock_file_is_auth_lock_alongside_token_db(self, tmp_path: Path) -> None:
        """contracts/configuration.md (T028): the advisory auth lock lives at
        ``auth.lock`` ALONGSIDE the token DB — not a ``<path>.lock`` sidecar.
        Locking the token DB path must create ``<dir>/auth.lock``."""
        db_path = tmp_path / "tokens.db"
        db_path.write_bytes(b"")  # token DB path; content irrelevant here

        with AuthLock(db_path):
            assert (tmp_path / "auth.lock").exists(), (
                "AuthLock must lock <dir-of-path>/auth.lock per "
                "contracts/configuration.md (T028)"
            )
            assert not (tmp_path / "tokens.db.lock").exists(), (
                "AuthLock must NOT use a <path>.lock sidecar (T028)"
            )

        assert not (tmp_path / "auth.lock").exists(), (
            "Lock file should be cleaned up after release"
        )

    def test_lock_path_lock_file_cleaned_up(self, tmp_path: Path) -> None:
        """The advisory lock file does not exist after the context exits."""
        lock_path = tmp_path / "auth.lock"
        with AuthLock(lock_path):
            pass
        assert not lock_path.exists(), (
            "Lock file should be cleaned up after release"
        )

    def test_concurrent_auth_error_is_actionable(self, tmp_path: Path) -> None:
        """ConcurrentAuthError carries the actionable message from the data model."""
        lock_path = tmp_path / "auth.lock"
        errors: list[ConcurrentAuthError] = []

        def acquire_second() -> None:
            try:
                with AuthLock(lock_path):
                    pass
            except ConcurrentAuthError as exc:
                errors.append(exc)

        with AuthLock(lock_path):
            t = threading.Thread(target=acquire_second)
            t.start()
            t.join()

        assert len(errors) == 1
        msg = str(errors[0])
        assert "authorization" in msg.lower() or "already" in msg.lower(), (
            f"Message should reference concurrent auth: {msg!r}"
        )


# ---------------------------------------------------------------------------
# retry_call — generalized bounded-retry helper
# ---------------------------------------------------------------------------


class TestRetryCall:
    """RED-phase tests for ``retry_call(fn, retries=2, ...)``.

    The ``retry_call`` helper generalises the existing ``retry_once`` so the
    caller can configure the number of retries.  Guarantees:

    * Initial attempt + exactly *retries* retries with short fixed waits.
    * :exc:`ConnectivityError <schwab_mcp.errors.ConnectivityError>` after
      exhaustion.
    * Stored credentials are **never** deleted/rewritten on failure (FR-006).

    These tests will fail (:exc:`ImportError`) until ``retry_call`` is
    implemented — this is the **RED** phase of TDD.
    """

    def test_retry_call_succeeds_on_first_attempt(self) -> None:
        """When ``fn`` succeeds on the first call, return the result
        without retrying."""
        from schwab_mcp.tokens import retry_call

        calls: list[object] = []

        def succeed() -> str:
            calls.append(None)
            return "ok"

        result = retry_call(succeed, retries=2)

        assert result == "ok"
        assert len(calls) == 1, "Should only call fn once on success"

    def test_retry_call_succeeds_after_retries(self) -> None:
        """When ``fn`` fails the first 2 times but succeeds on the 3rd
        call, return the result."""
        from schwab_mcp.tokens import retry_call

        calls: list[object] = []

        def fail_twice_then_succeed() -> str:
            calls.append(None)
            if len(calls) < 3:
                raise RuntimeError("transient error")
            return "ok"

        result = retry_call(fail_twice_then_succeed, retries=2)

        assert result == "ok"
        assert len(calls) == 3, (
            f"Expected 3 calls (initial + 2 retries), got {len(calls)}"
        )

    def test_retry_call_exhausts_retries(self) -> None:
        """When ``fn`` always fails, verify it is called exactly 3 times
        (initial + 2 retries) and raises :exc:`ConnectivityError`."""
        from schwab_mcp.errors import ConnectivityError
        from schwab_mcp.tokens import retry_call

        calls: list[object] = []

        def always_fail() -> str:
            calls.append(None)
            raise RuntimeError("persistent error")

        with pytest.raises(ConnectivityError):
            retry_call(always_fail, retries=2)

        assert len(calls) == 3, (
            f"Expected 3 calls (initial + 2 retries), "
            f"got {len(calls)}"
        )

    def test_retry_call_raises_connectivity_error(self) -> None:
        """After exhausting retries, the raised exception is an instance
        of :exc:`ConnectivityError`."""
        from schwab_mcp.errors import ConnectivityError
        from schwab_mcp.tokens import retry_call

        def always_fail() -> str:
            raise RuntimeError("persistent error")

        with pytest.raises(ConnectivityError) as excinfo:
            retry_call(always_fail, retries=2)

        assert isinstance(excinfo.value, ConnectivityError)

    def test_retry_call_stored_credentials_not_deleted(self, tmp_path: Path) -> None:
        """After retries are exhausted, verify the token store is NOT
        deleted or modified (FR-006)."""
        from schwab_mcp.tokens import retry_call

        token_store = tmp_path / "tokens.db"
        token_store.write_text("dummy token data")
        mtime_before = token_store.stat().st_mtime_ns

        def always_fail() -> str:
            raise RuntimeError("network error")

        with pytest.raises(Exception):
            retry_call(always_fail, retries=2)

        assert token_store.exists(), (
            "Token store was deleted on failure (FR-006)"
        )
        mtime_after = token_store.stat().st_mtime_ns
        assert mtime_after == mtime_before, (
            "Token store was modified on failure (FR-006)"
        )

    def test_retry_call_retries_with_short_waits(self, monkeypatch: object) -> None:
        """When ``fn`` fails, verify there is a short ``time.sleep`` wait
        between retries.  The actual delay is mocked away."""
        from schwab_mcp.tokens import retry_call

        sleep_times: list[float] = []

        def mock_sleep(seconds: float) -> None:
            sleep_times.append(seconds)

        monkeypatch.setattr("time.sleep", mock_sleep)  # type: ignore[arg-type]

        calls: list[object] = []

        def always_fail() -> str:
            calls.append(None)
            raise RuntimeError("transient")

        with pytest.raises(Exception):
            retry_call(always_fail, retries=2)

        assert len(sleep_times) == 2, (
            f"Expected a short wait before each of the 2 retries, "
            f"got {len(sleep_times)} sleep calls"
        )
        for s in sleep_times:
            assert s > 0, f"Wait time must be positive, got {s}"