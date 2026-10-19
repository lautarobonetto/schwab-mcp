"""Failing unit tests for RenewalOutcome and AuthHealth value types.

These are TDD red-phase tests: the source module (schwab_mcp.renewal) does
not exist yet, so every test will fail with ModuleNotFoundError / ImportError.
Once implemented, all tests should pass.

References
----------
- FR-004: payloads MUST NOT contain token/secret values or URLs.
- RenewalOutcome payload is exactly 3-4 fields on a single JSON line.
"""

from __future__ import annotations

import json
import threading
from unittest.mock import MagicMock

import pytest


# =============================================================================
# RenewalOutcome — value type for token renewal results
# =============================================================================


class TestRenewalOutcome:
    """RenewalOutcome(outcome, expires_in_seconds, retryable, detail) value type.

    A frozen value type that serialises to a single compact JSON line.
    """

    def test_renewed_outcome_retryable_false(self) -> None:
        """``renewed`` outcome: retryable must be False, detail is ``access_renewed``."""
        from schwab_mcp.renewal import RenewalOutcome

        outcome = RenewalOutcome(
            outcome="renewed",
            expires_in_seconds=1800,
            retryable=False,
            detail="access_renewed",
        )
        assert outcome.outcome == "renewed"
        assert outcome.expires_in_seconds == 1800
        assert outcome.retryable is False
        assert outcome.detail == "access_renewed"

    def test_not_needed_outcome_retryable_false(self) -> None:
        """``not_needed`` outcome: retryable must be False, detail is ``still_valid``."""
        from schwab_mcp.renewal import RenewalOutcome

        outcome = RenewalOutcome(
            outcome="not_needed",
            expires_in_seconds=3500,
            retryable=False,
            detail="still_valid",
        )
        assert outcome.outcome == "not_needed"
        assert outcome.expires_in_seconds == 3500
        assert outcome.retryable is False
        assert outcome.detail == "still_valid"

    def test_transient_failure_outcome_retryable_true(self) -> None:
        """``transient_failure`` outcome: retryable must be True, detail is ``provider_unreachable``."""
        from schwab_mcp.renewal import RenewalOutcome

        outcome = RenewalOutcome(
            outcome="transient_failure",
            expires_in_seconds=None,
            retryable=True,
            detail="provider_unreachable",
        )
        assert outcome.outcome == "transient_failure"
        assert outcome.expires_in_seconds is None
        assert outcome.retryable is True
        assert outcome.detail == "provider_unreachable"

    def test_reauth_required_outcome_retryable_false(self) -> None:
        """``reauth_required`` outcome: retryable must be False, detail is ``refresh_rejected``."""
        from schwab_mcp.renewal import RenewalOutcome

        outcome = RenewalOutcome(
            outcome="reauth_required",
            expires_in_seconds=None,
            retryable=False,
            detail="refresh_rejected",
        )
        assert outcome.outcome == "reauth_required"
        assert outcome.expires_in_seconds is None
        assert outcome.retryable is False
        assert outcome.detail == "refresh_rejected"

    def test_to_json_serialization(self) -> None:
        """to_json() returns a compact single-line JSON string with the right fields."""
        from schwab_mcp.renewal import RenewalOutcome

        outcome = RenewalOutcome(
            outcome="renewed",
            expires_in_seconds=1800,
            retryable=False,
            detail="access_renewed",
        )
        raw = outcome.to_json()
        parsed = json.loads(raw)

        assert isinstance(raw, str), "to_json() must return a string"
        assert "\n" not in raw, "to_json() must be a single line, no newlines"
        assert parsed["outcome"] == "renewed"
        assert parsed["expires_in_seconds"] == 1800
        assert parsed["retryable"] is False
        assert parsed["detail"] == "access_renewed"
        # Payload must be exactly 3-4 fields, single line (FR-004)
        assert 3 <= len(parsed) <= 4, "Payload must contain 3-4 fields"

    def test_from_json_deserialization(self) -> None:
        """Round-trip via to_json() and from_json() reconstructs an equal object."""
        from schwab_mcp.renewal import RenewalOutcome

        original = RenewalOutcome(
            outcome="transient_failure",
            expires_in_seconds=None,
            retryable=True,
            detail="provider_unreachable",
        )
        serialized = original.to_json()
        restored = RenewalOutcome.from_json(serialized)

        assert restored.outcome == original.outcome
        assert restored.expires_in_seconds == original.expires_in_seconds
        assert restored.retryable == original.retryable
        assert restored.detail == original.detail

    def test_invalid_outcome_raises(self) -> None:
        """Constructing with an outcome string not in the enum raises a validation error."""
        from schwab_mcp.renewal import RenewalOutcome

        with pytest.raises((ValueError, TypeError)):
            RenewalOutcome(
                outcome="bogus_outcome",
                expires_in_seconds=100,
                retryable=False,
                detail="access_renewed",
            )

    def test_invalid_detail_raises(self) -> None:
        """Constructing with a detail string not in the fixed vocabulary raises a validation error."""
        from schwab_mcp.renewal import RenewalOutcome

        with pytest.raises((ValueError, TypeError)):
            RenewalOutcome(
                outcome="renewed",
                expires_in_seconds=100,
                retryable=False,
                detail="bogus_detail",
            )

    def test_renewed_retryable_true_raises(self) -> None:
        """``renewed`` outcome with retryable=True must raise (rule: renewed implies not retryable)."""
        from schwab_mcp.renewal import RenewalOutcome

        with pytest.raises((ValueError, TypeError)):
            RenewalOutcome(
                outcome="renewed",
                expires_in_seconds=1800,
                retryable=True,
                detail="access_renewed",
            )

    def test_transient_failure_retryable_false_raises(self) -> None:
        """``transient_failure`` outcome with retryable=False must raise."""
        from schwab_mcp.renewal import RenewalOutcome

        with pytest.raises((ValueError, TypeError)):
            RenewalOutcome(
                outcome="transient_failure",
                expires_in_seconds=None,
                retryable=False,
                detail="provider_unreachable",
            )

    def test_negative_expires_in_seconds_raises(self) -> None:
        """A negative expires_in_seconds must raise a validation error (must be >= 0)."""
        from schwab_mcp.renewal import RenewalOutcome

        with pytest.raises((ValueError, TypeError)):
            RenewalOutcome(
                outcome="renewed",
                expires_in_seconds=-1,
                retryable=False,
                detail="access_renewed",
            )


# =============================================================================
# AuthHealth — value type for authentication health status
# =============================================================================


class TestAuthHealth:
    """AuthHealth(state, access_expires_in_seconds, refresh_expires_in_seconds) value type.

    A frozen value type that serialises to a single compact JSON line.
    """

    def test_valid_health(self) -> None:
        """``valid`` state with both expiry values present."""
        from schwab_mcp.renewal import AuthHealth

        health = AuthHealth(
            state="valid",
            access_expires_in_seconds=1520,
            refresh_expires_in_seconds=412000,
        )
        assert health.state == "valid"
        assert health.access_expires_in_seconds == 1520
        assert health.refresh_expires_in_seconds == 412000

    def test_reauth_required_health(self) -> None:
        """``reauth_required`` state with both expiry values as None."""
        from schwab_mcp.renewal import AuthHealth

        health = AuthHealth(
            state="reauth_required",
            access_expires_in_seconds=None,
            refresh_expires_in_seconds=None,
        )
        assert health.state == "reauth_required"
        assert health.access_expires_in_seconds is None
        assert health.refresh_expires_in_seconds is None

    def test_store_absent_health(self) -> None:
        """``store_absent`` state with both expiry values as None."""
        from schwab_mcp.renewal import AuthHealth

        health = AuthHealth(
            state="store_absent",
            access_expires_in_seconds=None,
            refresh_expires_in_seconds=None,
        )
        assert health.state == "store_absent"
        assert health.access_expires_in_seconds is None
        assert health.refresh_expires_in_seconds is None

    def test_store_corrupted_health(self) -> None:
        """``store_corrupted`` state with both expiry values as None."""
        from schwab_mcp.renewal import AuthHealth

        health = AuthHealth(
            state="store_corrupted",
            access_expires_in_seconds=None,
            refresh_expires_in_seconds=None,
        )
        assert health.state == "store_corrupted"
        assert health.access_expires_in_seconds is None
        assert health.refresh_expires_in_seconds is None

    def test_invalid_state_raises(self) -> None:
        """Constructing with a state string not in the enum raises a validation error."""
        from schwab_mcp.renewal import AuthHealth

        with pytest.raises((ValueError, TypeError)):
            AuthHealth(
                state="bogus_state",
                access_expires_in_seconds=None,
                refresh_expires_in_seconds=None,
            )

    def test_negative_access_expires_raises(self) -> None:
        """A negative access_expires_in_seconds must raise (must be >= 0 when present)."""
        from schwab_mcp.renewal import AuthHealth

        with pytest.raises((ValueError, TypeError)):
            AuthHealth(
                state="valid",
                access_expires_in_seconds=-5,
                refresh_expires_in_seconds=100,
            )

    def test_negative_refresh_expires_raises(self) -> None:
        """A negative refresh_expires_in_seconds must raise (must be >= 0 when present)."""
        from schwab_mcp.renewal import AuthHealth

        with pytest.raises((ValueError, TypeError)):
            AuthHealth(
                state="valid",
                access_expires_in_seconds=100,
                refresh_expires_in_seconds=-5,
            )

    def test_to_json_serialization(self) -> None:
        """to_json() returns a compact single-line JSON string with the right fields."""
        from schwab_mcp.renewal import AuthHealth

        health = AuthHealth(
            state="valid",
            access_expires_in_seconds=1520,
            refresh_expires_in_seconds=412000,
        )
        raw = health.to_json()
        parsed = json.loads(raw)

        assert isinstance(raw, str), "to_json() must return a string"
        assert "\n" not in raw, "to_json() must be a single line, no newlines"
        assert parsed["state"] == "valid"
        assert parsed["access_expires_in_seconds"] == 1520
        assert parsed["refresh_expires_in_seconds"] == 412000

    def test_from_json_deserialization(self) -> None:
        """Round-trip via to_json() and from_json() reconstructs an equal object."""
        from schwab_mcp.renewal import AuthHealth

        original = AuthHealth(
            state="reauth_required",
            access_expires_in_seconds=None,
            refresh_expires_in_seconds=None,
        )
        serialized = original.to_json()
        restored = AuthHealth.from_json(serialized)

        assert restored.state == original.state
        assert restored.access_expires_in_seconds == original.access_expires_in_seconds
        assert restored.refresh_expires_in_seconds == original.refresh_expires_in_seconds


# =============================================================================
# read_store_lifetime — token lifetime reader from SQLite store
# =============================================================================


class TestStoreLifetimeReader:
    """Tests for read_store_lifetime() — reads token lifetime data from the
    schwabdev SQLite store.

    The function reads ``expires_in``, ``access_token_issued``, and
    ``refresh_token_issued`` from the ``schwabdev`` table and computes
    remaining seconds for both access and refresh tokens.
    """

    @staticmethod
    def _seed_store(
        path: str,
        *,
        expires_in: int = 1800,
        access_age: float = 100.0,
        refresh_age: float = 3600.0,
    ) -> None:
        """Create a real SQLite token store with known timing values.

        Parameters
        ----------
        path
            File path for the new SQLite database.
        expires_in
            Provider-communicated lifetime in seconds (default 1800).
        access_age
            Seconds since access_token_issued (default 100).
        refresh_age
            Seconds since refresh_token_issued (default 3600 = 1 hour).
        """
        import sqlite3
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        con = sqlite3.connect(str(path))
        # Real schwabdev 4.0.0 schema: issued timestamps are ISO-8601 TEXT.
        con.execute(
            "CREATE TABLE schwabdev ("
            "  access_token_issued TEXT NOT NULL,"
            "  refresh_token_issued TEXT NOT NULL,"
            "  access_token TEXT NOT NULL,"
            "  refresh_token TEXT NOT NULL,"
            "  id_token TEXT NOT NULL,"
            "  expires_in INTEGER,"
            "  token_type TEXT,"
            "  scope TEXT"
            ")"
        )
        con.execute(
            "INSERT INTO schwabdev VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (now - timedelta(seconds=access_age)).isoformat(),
                (now - timedelta(seconds=refresh_age)).isoformat(),
                "access_tok",
                "refresh_tok",
                "id_tok",
                expires_in,
                "bearer",
                "scope",
            ),
        )
        con.commit()
        con.close()

    def test_reads_lifetime_from_store(self, tmp_path) -> None:
        """A valid store returns computed remaining seconds for both access and refresh."""
        from schwab_mcp.renewal import read_store_lifetime

        db = tmp_path / "schwabdev.db"
        self._seed_store(db, expires_in=1800, access_age=100, refresh_age=3600)

        result = read_store_lifetime(db)

        assert result is not None
        # access: 1800 - 100 = 1700
        assert result.access_remaining_seconds == pytest.approx(1700, abs=2)
        # refresh: 7*24*3600 - 3600 = 601200
        assert result.refresh_remaining_seconds == pytest.approx(601200, abs=2)

    def test_returns_none_for_absent_store(self, tmp_path) -> None:
        """A non-existent file path returns None."""
        from schwab_mcp.renewal import read_store_lifetime

        result = read_store_lifetime(tmp_path / "nonexistent.db")
        assert result is None

    def test_returns_none_for_corrupted_store(self, tmp_path) -> None:
        """A corrupted/invalid SQLite file returns None (FR-009 — no crash)."""
        from schwab_mcp.renewal import read_store_lifetime

        db = tmp_path / "corrupted.db"
        db.write_text("this is not a valid sqlite database")

        result = read_store_lifetime(db)
        assert result is None

    def test_access_remaining_seconds_computed_correctly(self, tmp_path) -> None:
        """Access remaining = expires_in - (now - access_token_issued)."""
        from schwab_mcp.renewal import read_store_lifetime

        db = tmp_path / "schwabdev.db"
        # access issued 100 s ago, expires_in = 1800 → remaining ≈ 1700
        self._seed_store(db, expires_in=1800, access_age=100, refresh_age=100)

        result = read_store_lifetime(db)
        assert result is not None
        assert result.access_remaining_seconds == pytest.approx(1700, abs=2)

    def test_reads_real_schwabdev_iso_timestamp_schema(self, tmp_path) -> None:
        """Regression: real schwabdev stores issued timestamps as ISO-8601 TEXT.

        The production schema is ``access_token_issued TEXT NOT NULL`` /
        ``refresh_token_issued TEXT NOT NULL`` holding values like
        ``2026-10-19T22:00:27.004577+00:00``.  The reader must parse them
        instead of subtracting from a float (float - str TypeError).
        """
        import sqlite3
        from datetime import datetime, timedelta, timezone

        from schwab_mcp.renewal import read_store_lifetime

        db = tmp_path / "schwabdev.db"
        now = datetime.now(timezone.utc)
        access_issued = (now - timedelta(seconds=100)).isoformat()
        refresh_issued = (now - timedelta(seconds=3600)).isoformat()
        con = sqlite3.connect(str(db))
        con.execute(
            "CREATE TABLE schwabdev ("
            "  access_token_issued TEXT NOT NULL,"
            "  refresh_token_issued TEXT NOT NULL,"
            "  access_token TEXT NOT NULL,"
            "  refresh_token TEXT NOT NULL,"
            "  id_token TEXT NOT NULL,"
            "  expires_in INTEGER,"
            "  token_type TEXT,"
            "  scope TEXT"
            ")"
        )
        con.execute(
            "INSERT INTO schwabdev VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                access_issued,
                refresh_issued,
                "access_tok",
                "refresh_tok",
                "id_tok",
                1800,
                "bearer",
                "scope",
            ),
        )
        con.commit()
        con.close()

        result = read_store_lifetime(db)

        assert result is not None
        # access: 1800 - 100 = 1700
        assert result.access_remaining_seconds == pytest.approx(1700, abs=2)
        # refresh: 7*24*3600 - 3600 = 601200
        assert result.refresh_remaining_seconds == pytest.approx(601200, abs=2)

    def test_returns_none_for_unparseable_issued_timestamps(self, tmp_path) -> None:
        """Unparseable issued timestamps yield None (treated as corrupted), never a crash."""
        import sqlite3

        from schwab_mcp.renewal import read_store_lifetime

        db = tmp_path / "schwabdev.db"
        con = sqlite3.connect(str(db))
        con.execute(
            "CREATE TABLE schwabdev ("
            "  access_token_issued TEXT NOT NULL,"
            "  refresh_token_issued TEXT NOT NULL,"
            "  access_token TEXT NOT NULL,"
            "  refresh_token TEXT NOT NULL,"
            "  id_token TEXT NOT NULL,"
            "  expires_in INTEGER,"
            "  token_type TEXT,"
            "  scope TEXT"
            ")"
        )
        con.execute(
            "INSERT INTO schwabdev VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "not-a-timestamp",
                "also-not",
                "access_tok",
                "refresh_tok",
                "id_tok",
                1800,
                "bearer",
                "scope",
            ),
        )
        con.commit()
        con.close()

        result = read_store_lifetime(db)
        assert result is None

    def test_refresh_remaining_seconds_computed_correctly(self, tmp_path) -> None:
        """Refresh remaining = 7*24*3600 - (now - refresh_token_issued)."""
        from schwab_mcp.renewal import read_store_lifetime

        db = tmp_path / "schwabdev.db"
        # refresh issued 1 hour ago → remaining ≈ 7*24*3600 - 3600
        self._seed_store(db, expires_in=1800, access_age=100, refresh_age=3600)

        result = read_store_lifetime(db)
        assert result is not None
        expected = 7 * 24 * 3600 - 3600  # 601200
        assert result.refresh_remaining_seconds == pytest.approx(expected, abs=2)


# =============================================================================
# renew() — renewal orchestration function (RED phase — fails to import)
# =============================================================================


class TestRenew:
    """Tests for renew() — the renewal orchestration function.

    These tests pass once ``renew()`` is implemented.  Every
    classification path is covered.

    References
    ----------
    - FR-003: Outcome classification into one of four classes.
    - FR-005: Single-flight — at most one renewal in flight at any time.
    - FR-011: Transparent to the caller.
    - research.md D2: Three-signal classification scheme.
    """

    @staticmethod
    def _seed_store(
        path: str,
        *,
        expires_in: int = 1800,
        access_age: float = 100.0,
        refresh_age: float = 3600.0,
    ) -> None:
        """Create or re-seed a real SQLite token store with known timing values.

        Uses ``CREATE TABLE IF NOT EXISTS`` and ``DELETE`` first so it can
        be called multiple times on the same path (required for single-flight
        tests where a side effect updates the store mid-flight).

        Parameters
        ----------
        path
            File path for the new SQLite database.
        expires_in
            Provider-communicated lifetime in seconds (default 1800).
        access_age
            Seconds since access_token_issued (default 100).
        refresh_age
            Seconds since refresh_token_issued (default 3600 = 1 hour).
        """
        import sqlite3
        import time

        now = time.time()
        con = sqlite3.connect(str(path))
        con.execute(
            "CREATE TABLE IF NOT EXISTS schwabdev ("
            "  expires_in INT,"
            "  access_token_issued REAL,"
            "  refresh_token_issued REAL,"
            "  access_token TEXT,"
            "  refresh_token TEXT,"
            "  id_token TEXT,"
            "  token_type TEXT,"
            "  scope TEXT"
            ")"
        )
        con.execute("DELETE FROM schwabdev")
        con.execute(
            "INSERT INTO schwabdev VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                expires_in,
                now - access_age,
                now - refresh_age,
                "access_tok",
                "refresh_tok",
                "id_tok",
                "bearer",
                "scope",
            ),
        )
        con.commit()
        con.close()

    def test_renewed_outcome_when_update_tokens_returns_true(self, tmp_path) -> None:
        """``update_tokens()`` returns ``True`` → outcome ``renewed`` with detail ``access_renewed`` and ``retryable=False``."""
        from schwab_mcp.renewal import RenewalOutcome, renew

        db = tmp_path / "schwabdev.db"
        # Access token about to expire (10 s remaining → below 61 s margin)
        self._seed_store(db, expires_in=1800, access_age=1790, refresh_age=3600)

        client = MagicMock()
        client.update_tokens.return_value = True

        result = renew(client, str(db))

        assert isinstance(result, RenewalOutcome)
        assert result.outcome == "renewed"
        assert result.detail == "access_renewed"
        assert result.retryable is False
        assert result.expires_in_seconds is not None

    def test_not_needed_when_above_margin(self, tmp_path) -> None:
        """Above-margin remaining validity → ``not_needed`` detail ``still_valid``, no network call."""
        from schwab_mcp.renewal import RenewalOutcome, renew

        db = tmp_path / "schwabdev.db"
        # Access token well above 61 s margin (1700 s remaining)
        self._seed_store(db, expires_in=1800, access_age=100, refresh_age=3600)

        client = MagicMock()

        result = renew(client, str(db))

        assert isinstance(result, RenewalOutcome)
        assert result.outcome == "not_needed"
        assert result.detail == "still_valid"
        assert result.retryable is False
        client.update_tokens.assert_not_called()

    def test_transient_failure_after_retries_exhausted(self, tmp_path) -> None:
        """Persistent network error → ``retry_call`` exhausts → ``transient_failure`` with ``retryable=True``."""
        from schwab_mcp.renewal import RenewalOutcome, renew

        db = tmp_path / "schwabdev.db"
        self._seed_store(db, expires_in=1800, access_age=1790, refresh_age=3600)

        client = MagicMock()
        client.update_tokens.side_effect = ConnectionError("network error")

        result = renew(client, str(db))

        assert isinstance(result, RenewalOutcome)
        assert result.outcome == "transient_failure"
        assert result.retryable is True
        assert result.detail == "provider_unreachable"

    def test_reauth_required_when_guard_hook_raises(self, tmp_path) -> None:
        """Guard hook raises ``ReauthorizationRequiredError`` → ``reauth_required`` detail ``reauth_needed``."""
        from schwab_mcp.errors import ReauthorizationRequiredError
        from schwab_mcp.renewal import RenewalOutcome, renew

        db = tmp_path / "schwabdev.db"
        self._seed_store(db, expires_in=1800, access_age=1790, refresh_age=3600)

        client = MagicMock()
        client.update_tokens.side_effect = ReauthorizationRequiredError()

        result = renew(client, str(db))

        assert isinstance(result, RenewalOutcome)
        assert result.outcome == "reauth_required"
        assert result.detail == "reauth_needed"
        assert result.retryable is False

    def test_renewed_via_tie_breaker_probe(self, tmp_path) -> None:
        """``update_tokens()`` returns ``False`` but ``linked_accounts()`` succeeds → ``renewed`` (another process already renewed)."""
        from schwab_mcp.renewal import RenewalOutcome, renew

        db = tmp_path / "schwabdev.db"
        self._seed_store(db, expires_in=1800, access_age=1790, refresh_age=3600)

        client = MagicMock()
        client.update_tokens.return_value = False
        client.linked_accounts.return_value = {"accounts": []}

        result = renew(client, str(db))

        assert isinstance(result, RenewalOutcome)
        assert result.outcome == "renewed"
        assert result.detail == "access_renewed"
        assert result.retryable is False

    def test_single_flight_sharing(self, tmp_path) -> None:
        """Concurrent callers to ``renew()`` result in exactly one renewal (FR-005).

        Two threads synchronise on a barrier so they enter ``renew()`` at
        nearly the same time.  The first thread performs the renewal while
        the second waits; after the first completes, the second re-reads the
        store and finds a fresh token, avoiding a duplicate network call.
        """
        from schwab_mcp.renewal import renew

        db = tmp_path / "schwabdev.db"
        self._seed_store(db, expires_in=1800, access_age=1790, refresh_age=3600)

        client = MagicMock()

        def _slow_update_tokens() -> bool:
            """Simulate a network-round-trip delay and update the store
            as a side effect (mirrors what ``schwabdev`` does internally)."""
            import time

            time.sleep(0.3)
            # Simulate the store being updated by the successful renewal
            self._seed_store(db, expires_in=1800, access_age=0, refresh_age=3600)
            return True

        client.update_tokens.side_effect = _slow_update_tokens

        barrier = threading.Barrier(2)
        results: list[object] = []

        def _call_renew() -> None:
            barrier.wait()
            results.append(renew(client, str(db)))

        threads = [threading.Thread(target=_call_renew) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert client.update_tokens.call_count == 1, (
            f"Expected exactly one renewal call, got {client.update_tokens.call_count}"
        )
        assert len(results) == 2
        assert all(r.outcome in ("renewed", "not_needed") for r in results)