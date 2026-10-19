"""Failing integration tests for the automatic renewal flow (User Story 1 / T009).

These tests verify the ``renew()`` orchestration function in
``schwab_mcp.renewal``: operations through a stub client with a stale access
credential succeed transparently (FR-011).

The module-level import below WILL raise ``ImportError`` because
``schwab_mcp.renewal.renew`` does not exist yet — every test in this file
fails at import time during the TDD red phase for T009 (US1).

After implementation (T010), these tests should pass and cover:

1. Exactly one renewal occurs when the access credential is stale.
2. The operation result shape is unchanged by the renewal.
3. Stderr carries ``renew_start`` → ``renewal_success outcome=ok`` event
   lines (contracts/events.md).
4. Zero secret material appears in any output channel (FR-004, FR-006).

References
----------
- FR-011: Authenticated operations that trigger an automatic renewal MUST
  complete transparently — result shape unchanged, no extra agent steps.
- contracts/events.md : Renewal event line format and vocabulary.
- FR-004 / FR-006 : Zero secrets in outputs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# This import WILL raise ImportError because ``schwab_mcp.renewal.renew``
# does not exist yet.  Every test in this file fails at import time during
# the TDD red phase for T009 (US1).
# ---------------------------------------------------------------------------
from schwab_mcp.renewal import renew


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_expired_token_db(path: Path) -> Path:
    """Create a token store with an expired access token but valid refresh.

    The ``access_token_issued`` timestamp is set far in the past so that
    the 1800-second lifetime has long elapsed.  Uses REAL timestamps
    (Unix seconds) consistent with ``read_store_lifetime``.
    """
    import sqlite3
    import time

    now = time.time()
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
        # Access token issued 2 hours ago (6000+ s) with 1800 s lifetime → expired
        # Refresh token issued 1 hour ago → still valid (7-day lifetime)
        con.execute(
            "INSERT INTO schwabdev VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "expired-access-token",
                "valid-refresh-token",
                "expired-id-token",
                now - 7200,          # 2 hours ago
                now - 3600,          # 1 hour ago
                1800,
                "Bearer",
                "readonly",
            ),
        )
        con.commit()
    finally:
        con.close()
    return path


def _stale_credential_client(store_path: str) -> mock.Mock:
    """Return a mock schwabdev Client with stale credentials.

    The mock behaves like a real client whose access credential has
    expired:
    - ``update_tokens()`` returns ``True`` (simulates successful renewal).
    - ``linked_accounts()`` returns a minimal valid response.
    - ``tokens_db`` points to the token store at *store_path*.
    """
    client = mock.Mock()
    client.update_tokens.return_value = True
    client.linked_accounts.return_value = {
        "accounts": [{"accountNumber": "12345678", "type": "MARGIN"}]
    }
    client.tokens_db = store_path
    return client


def _make_stderr_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    """Install a print hook that captures only stderr lines.

    Returns a list that the test can inspect after ``renew()`` runs.
    """
    captured: list[str] = []

    def tracking_print(*args: Any, **kwargs: Any) -> None:
        file = kwargs.get("file", sys.stdout)
        text = " ".join(str(a) for a in args)
        if file is sys.stderr:
            captured.append(text)

    monkeypatch.setattr("builtins.print", tracking_print)
    return captured


def _make_full_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[str], list[str]]:
    """Install a print hook that captures both stdout and stderr.

    Returns ``(captured_stdout, captured_stderr)``.
    """
    captured_stdout: list[str] = []
    captured_stderr: list[str] = []

    def tracking_print(*args: Any, **kwargs: Any) -> None:
        file = kwargs.get("file", sys.stdout)
        text = " ".join(str(a) for a in args)
        if file is sys.stderr:
            captured_stderr.append(text)
        else:
            captured_stdout.append(text)

    monkeypatch.setattr("builtins.print", tracking_print)
    return captured_stdout, captured_stderr


# ===================================================================
# TestAutomaticRenewal
# ===================================================================


class TestAutomaticRenewal:
    """Operations through a stale access credential trigger automatic
    renewal that succeeds transparently (FR-011)."""

    def test_stale_access_triggers_exactly_one_renewal(
        self, tmp_path: Path
    ) -> None:
        """A stale access credential triggers exactly one renewal when
        ``renew()`` is called (FR-011)."""
        store = _make_expired_token_db(tmp_path / "tokens.db")
        client = _stale_credential_client(str(store))

        result = renew(client)

        # Exactly one renewal attempt must have occurred
        assert client.update_tokens.call_count == 1, (
            f"Expected exactly one call to update_tokens(), "
            f"got {client.update_tokens.call_count}"
        )
        # The outcome must be "renewed" (successful refresh)
        assert result.outcome == "renewed", (
            f"Expected outcome 'renewed', got {result.outcome!r}"
        )
        # No other side effects
        assert client.linked_accounts.call_count == 0, (
            "No linked_accounts call expected during a successful renewal"
        )

    def test_operation_result_unchanged_after_renewal(
        self, tmp_path: Path
    ) -> None:
        """After renewal, ``linked_accounts()`` returns the same result
        shape as without renewal (FR-011)."""
        store = _make_expired_token_db(tmp_path / "tokens.db")
        client = _stale_credential_client(str(store))

        # Perform the renewal
        renew(client)

        # The operation must still return the expected result shape
        result = client.linked_accounts()

        assert result == {
            "accounts": [{"accountNumber": "12345678", "type": "MARGIN"}]
        }, (
            f"Operation result shape changed after renewal (FR-011); "
            f"got {result}"
        )

    def test_stderr_contains_renewal_events(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stderr must contain ``auth_event=renew_start`` and
        ``auth_event=renewal_success outcome=ok`` event lines
        (contracts/events.md)."""
        store = _make_expired_token_db(tmp_path / "tokens.db")
        client = _stale_credential_client(str(store))

        captured_stderr = _make_stderr_capture(monkeypatch)

        renew(client)

        stderr_text = "\n".join(captured_stderr)

        # Must contain the renewal start event
        assert "auth_event=renew_start" in stderr_text, (
            "Expected 'auth_event=renew_start' in stderr output "
            f"(contracts/events.md), got:\n{stderr_text}"
        )
        # Must contain the renewal success event with ok outcome
        assert "auth_event=renewal_success" in stderr_text, (
            "Expected 'auth_event=renewal_success' in stderr output "
            f"(contracts/events.md), got:\n{stderr_text}"
        )
        assert "outcome=ok" in stderr_text, (
            "Expected 'outcome=ok' in stderr output "
            f"(contracts/events.md), got:\n{stderr_text}"
        )

    def test_no_secrets_in_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No token or secret material appears in any output channel
        (FR-004, FR-006)."""
        store = _make_expired_token_db(tmp_path / "tokens.db")
        client = _stale_credential_client(str(store))

        captured_stdout, captured_stderr = _make_full_capture(monkeypatch)

        renew(client)

        all_output = "\n".join(captured_stdout + captured_stderr)

        # None of the actual token/secret values may appear in output
        secrets = [
            "expired-access-token",
            "valid-refresh-token",
            "expired-id-token",
        ]
        for secret in secrets:
            assert secret not in all_output, (
                f"Secret {secret!r} leaked into output (FR-004, FR-006)\n"
                f"Got:\n{all_output}"
            )