"""Performance tests for the SC-002 renewal budget (≤ 10 s worst case)."""

from __future__ import annotations

import time
from unittest import mock

import pytest

from schwab_mcp.renewal import RenewalOutcome, renew


class TestRenewalBudget:
    """SC-002: worst-case renewal must complete in ≤ 10 s."""

    @pytest.mark.performance
    def test_renewal_completes_under_budget(self, tmp_path) -> None:
        """Worst-case renewal (3 attempts × 3 s + 2 × 0.5 s waits) ≤ 10 s."""
        # Create a valid but expired token store so renewal is triggered
        import sqlite3
        import time as _time

        now = _time.time()
        db = tmp_path / "tokens.db"
        con = sqlite3.connect(str(db))
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
            (30, now - 7200, now - 3600, "tok", "tok", "tok", "Bearer", "scope"),
        )
        con.commit()
        con.close()

        client = mock.MagicMock()
        client.update_tokens.side_effect = ConnectionError("timeout")

        start = time.time()
        result = renew(client, str(db))
        elapsed = time.time() - start

        assert isinstance(result, RenewalOutcome)
        assert result.outcome == "transient_failure"
        assert elapsed <= 10, f"Renewal took {elapsed:.2f}s, budget is 10 s"

    @pytest.mark.performance
    def test_renewal_success_is_fast(self, tmp_path) -> None:
        """A successful renewal (no retries) completes in < 1 s."""
        import sqlite3
        import time as _time

        now = _time.time()
        db = tmp_path / "tokens.db"
        con = sqlite3.connect(str(db))
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
            (30, now - 7200, now - 3600, "tok", "tok", "tok", "Bearer", "scope"),
        )
        con.commit()
        con.close()

        client = mock.MagicMock()
        client.update_tokens.return_value = True

        start = time.time()
        result = renew(client, str(db))
        elapsed = time.time() - start

        assert result.outcome == "renewed"
        assert elapsed < 1, f"Success took {elapsed:.2f}s, expected < 1 s"