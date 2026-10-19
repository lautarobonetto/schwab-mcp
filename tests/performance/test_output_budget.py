"""Performance tests for output size budgets (Principle V)."""

from __future__ import annotations

import json

import pytest

from schwab_mcp.renewal import AuthHealth, RenewalOutcome


class TestOutputBudget:
    """Principle V: Renewal and auth-status JSON outputs are compact
    (single line, ≤ 300 bytes, ≤ 4 fields)."""

    def _assert_compact(self, json_str: str, max_fields: int = 4) -> None:
        """Assert *json_str* is a single line, ≤ 300 bytes, with ≤ *max_fields* keys."""
        assert "\n" not in json_str, "Must be a single line"
        byte_len = len(json_str.encode("utf-8"))
        assert byte_len <= 300, f"Must be ≤300 bytes, got {byte_len}"
        keys = set(json.loads(json_str).keys())
        assert len(keys) <= max_fields, f"Must have ≤{max_fields} fields, got {len(keys)}"

    @pytest.mark.performance
    def test_renewed_output_compact(self) -> None:
        outcome = RenewalOutcome(
            outcome="renewed",
            expires_in_seconds=1800,
            retryable=False,
            detail="access_renewed",
        )
        self._assert_compact(outcome.to_json())

    @pytest.mark.performance
    def test_not_needed_output_compact(self) -> None:
        outcome = RenewalOutcome(
            outcome="not_needed",
            expires_in_seconds=3500,
            retryable=False,
            detail="still_valid",
        )
        self._assert_compact(outcome.to_json())

    @pytest.mark.performance
    def test_transient_failure_output_compact(self) -> None:
        outcome = RenewalOutcome(
            outcome="transient_failure",
            expires_in_seconds=None,
            retryable=True,
            detail="provider_unreachable",
        )
        self._assert_compact(outcome.to_json())

    @pytest.mark.performance
    def test_reauth_required_output_compact(self) -> None:
        outcome = RenewalOutcome(
            outcome="reauth_required",
            expires_in_seconds=None,
            retryable=False,
            detail="reauth_needed",
        )
        self._assert_compact(outcome.to_json())

    @pytest.mark.performance
    def test_auth_valid_output_compact(self) -> None:
        health = AuthHealth(
            state="valid",
            access_expires_in_seconds=1520,
            refresh_expires_in_seconds=412000,
        )
        self._assert_compact(health.to_json())

    @pytest.mark.performance
    def test_auth_reauth_output_compact(self) -> None:
        health = AuthHealth(
            state="reauth_required",
            access_expires_in_seconds=None,
            refresh_expires_in_seconds=None,
        )
        self._assert_compact(health.to_json())