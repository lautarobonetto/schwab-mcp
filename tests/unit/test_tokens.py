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
from schwab_mcp.tokens import (
    AuthLock,
    _read_schwabdev_row,
    enforce_permissions,
    peek_store_status,
)


def _make_full_schema_store(
    path: Path,
    *,
    access_issued: object = "2026-11-03T00:00:00+00:00",
    refresh_issued: object = "2026-11-03T00:00:00+00:00",
    expires_in: object = 1800,
) -> None:
    """Create a store with the real schwabdev schema and configurable
    issued-timestamp values (defaults: loadable ISO-8601 text)."""
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
                "a", "r", "i",
                access_issued, refresh_issued, expires_in,
                "Bearer", "scope",
            ),
        )
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# _read_schwabdev_row (TD-003 — single store-read implementation)
# ---------------------------------------------------------------------------


class TestReadSchwabdevRow:
    """_read_schwabdev_row(path) → ("absent", None) | ("corrupted", None) | ("present", row).

    TD-003: one implementation of the store-read contract (stat → empty
    check → read-only connect → query → close), shared by
    ``peek_store_status`` and ``renewal.read_store_lifetime``.
    """

    def test_absent_for_missing_file(self, tmp_path: Path) -> None:
        status, row = _read_schwabdev_row(tmp_path / "does-not-exist.db")
        assert (status, row) == ("absent", None)

    def test_absent_for_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.db"
        path.write_bytes(b"")
        status, row = _read_schwabdev_row(path)
        assert (status, row) == ("absent", None)

    def test_corrupted_for_non_sqlite_bytes(self, tmp_path: Path) -> None:
        """FR-009: unparseable content → corrupted, never a crash."""
        path = tmp_path / "corrupted.db"
        path.write_bytes(b"not a database")
        status, row = _read_schwabdev_row(path)
        assert (status, row) == ("corrupted", None)

    def test_corrupted_for_missing_schwabdev_table(self, tmp_path: Path) -> None:
        """Valid SQLite but no schwabdev table → corrupted (loader cannot read a row)."""
        path = tmp_path / "wrong-schema.db"
        con = sqlite3.connect(str(path))
        try:
            con.execute("CREATE TABLE other (x TEXT)")
            con.commit()
        finally:
            con.close()
        status, row = _read_schwabdev_row(path)
        assert (status, row) == ("corrupted", None)

    def test_absent_for_empty_schwabdev_table(self, tmp_path: Path) -> None:
        path = tmp_path / "empty-table.db"
        con = sqlite3.connect(str(path))
        try:
            con.execute(
                "CREATE TABLE schwabdev (expires_in INTEGER,"
                " access_token_issued TEXT, refresh_token_issued TEXT)"
            )
            con.commit()
        finally:
            con.close()
        status, row = _read_schwabdev_row(path)
        assert (status, row) == ("absent", None)

    def test_present_row_for_full_schema_store(self, tmp_path: Path) -> None:
        path = tmp_path / "valid.db"
        _make_full_schema_store(path)
        status, row = _read_schwabdev_row(path)
        assert status == "present"
        assert row == (1800, "2026-11-03T00:00:00+00:00", "2026-11-03T00:00:00+00:00")


class TestStoreReadEquivalence:
    """TD-003 lock-in: ``peek_store_status`` consumes ``_read_schwabdev_row``
    and keeps its tri-state semantics, and the ``run_auth`` success gate
    (``peek_store_status(...) != "absent"``) matches the deleted
    ``peek_store`` on reachable states (absent/present)."""

    @staticmethod
    def _fixture(tmp_path: Path, kind: str) -> Path:
        path = tmp_path / "store.db"
        if kind == "missing":
            return path
        if kind == "empty":
            path.write_bytes(b"")
        elif kind == "garbage":
            path.write_bytes(b"not a database")
        elif kind == "no-table":
            con = sqlite3.connect(str(path))
            try:
                con.execute("CREATE TABLE other (x TEXT)")
                con.commit()
            finally:
                con.close()
        elif kind == "empty-table":
            con = sqlite3.connect(str(path))
            try:
                con.execute(
                    "CREATE TABLE schwabdev (expires_in INTEGER,"
                    " access_token_issued TEXT, refresh_token_issued TEXT)"
                )
                con.commit()
            finally:
                con.close()
        else:  # valid
            _make_full_schema_store(path)
        return path

    @pytest.mark.parametrize(
        ("kind", "expected"),
        [
            ("missing", "absent"),
            ("empty", "absent"),
            ("garbage", "corrupted"),
            ("no-table", "corrupted"),
            ("empty-table", "absent"),
            ("valid", "present"),
        ],
    )
    def test_peek_store_status_aligns_with_helper(
        self, tmp_path: Path, kind: str, expected: str
    ) -> None:
        path = self._fixture(tmp_path, kind)
        status, _row = _read_schwabdev_row(path)
        assert peek_store_status(path) == expected
        # The helper's structural status drives peek_store_status; the only
        # refinement it adds is ISO-timestamp validation, which can downgrade
        # "present" to "corrupted" but never upgrades the other two.
        if expected != "present":
            assert status == expected

    @pytest.mark.parametrize(
        ("kind", "store_missing"),
        [
            ("missing", True),
            ("empty", True),
            ("empty-table", True),
            ("garbage", False),
            ("no-table", False),
            ("valid", False),
        ],
    )
    def test_auth_gate_expression_semantics(
        self, tmp_path: Path, kind: str, store_missing: bool
    ) -> None:
        """Documents the run_auth gate translation (TD-003): the deleted
        ``not peek_store(...)`` ("no row") becomes
        ``peek_store_status(...) == "absent"`` — exact parity on reachable
        states (absent / present).  Corrupted stores are unreachable in
        run_auth: they are quarantined before the flow (cli.py) and the
        store is moved aside by backup_token_store before the gate is
        evaluated; the old bool collapsed them into "missing" while the
        status check reports them as "corrupted"."""
        path = self._fixture(tmp_path, kind)
        assert (peek_store_status(path) == "absent") is store_missing


# ---------------------------------------------------------------------------
# peek_store_status
# ---------------------------------------------------------------------------


class TestPeekStoreStatus:
    """peek_store_status(path) → "absent" | "present" | "corrupted".

    Bug store-unparseable-timestamps: the "present" classification requires
    the row to be *loadable* by the only real consumer (schwabdev parses
    ``*_token_issued`` as ISO-8601 text during ``Client.__init__``), not
    merely structurally valid.
    """

    def test_absent_for_missing_file(self, tmp_path: Path) -> None:
        from schwab_mcp.tokens import peek_store_status

        assert peek_store_status(tmp_path / "missing.db") == "absent"

    def test_corrupted_for_non_sqlite_content(self, tmp_path: Path) -> None:
        from schwab_mcp.tokens import peek_store_status

        path = tmp_path / "corrupted.db"
        path.write_bytes(b"not a database")
        assert peek_store_status(path) == "corrupted"

    def test_present_for_loadable_iso_timestamps(self, tmp_path: Path) -> None:
        from schwab_mcp.tokens import peek_store_status

        path = tmp_path / "valid.db"
        _make_full_schema_store(path)
        assert peek_store_status(path) == "present"

    def test_corrupted_for_numeric_epoch_text(self, tmp_path: Path) -> None:
        """Numeric epoch TEXT (observed live 2026-11-03: '1793726428') is
        unloadable by schwabdev's ``_parse_dt`` → corrupted, so the CLI
        classifies instead of crashing inside client construction."""
        from schwab_mcp.tokens import peek_store_status

        path = tmp_path / "epoch-text.db"
        _make_full_schema_store(path, access_issued="1793726428")
        assert peek_store_status(path) == "corrupted"

    def test_corrupted_for_numeric_epoch_real(self, tmp_path: Path) -> None:
        """A REAL-typed epoch value is equally unloadable
        (``fromisoformat`` rejects non-str) → corrupted."""
        from schwab_mcp.tokens import peek_store_status

        path = tmp_path / "epoch-real.db"
        _make_full_schema_store(path, access_issued=1793726428.0)
        assert peek_store_status(path) == "corrupted"

    def test_corrupted_for_null_timestamp(self, tmp_path: Path) -> None:
        from schwab_mcp.tokens import peek_store_status

        path = tmp_path / "null-issued.db"
        _make_full_schema_store(path, refresh_issued=None)
        assert peek_store_status(path) == "corrupted"

    def test_present_for_null_expires_in(self, tmp_path: Path) -> None:
        """``expires_in`` is not consumed by the loader at load time
        (schwabdev reads it with a ``get(..., 1800)`` default when
        writing) — NULL must NOT classify as corrupted."""
        from schwab_mcp.tokens import peek_store_status

        path = tmp_path / "null-expires.db"
        _make_full_schema_store(path, expires_in=None)
        assert peek_store_status(path) == "present"

    def test_corrupted_for_missing_timestamp_columns(self, tmp_path: Path) -> None:
        """A schema without the issued columns cannot be loaded → corrupted."""
        from schwab_mcp.tokens import peek_store_status

        path = tmp_path / "minimal-schema.db"
        con = sqlite3.connect(str(path))
        try:
            con.execute("CREATE TABLE schwabdev (access_token TEXT, refresh_token TEXT)")
            con.execute("INSERT INTO schwabdev VALUES ('a', 'r')")
            con.commit()
        finally:
            con.close()
        assert peek_store_status(path) == "corrupted"


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

    The ``retry_call`` helper lets the caller configure the number of
    retries.  Guarantees:

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