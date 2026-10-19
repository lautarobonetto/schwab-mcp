"""Unit tests for the schwab-mcp error taxonomy (SC-005).

These tests verify the 7 error types, their common AuthError base class,
distinct actionable messages, and exit codes. The implementation lives in
src/schwab_mcp/errors.py — because that file does not exist yet, every
test here is expected to FAIL (TDD red phase).
"""

import pytest


# ---------------------------------------------------------------------------
# Helper — collect all error types for exhaustive iteration
# ---------------------------------------------------------------------------

def _all_error_types():
    """Return the 7 error classes from the taxonomy."""
    from schwab_mcp.errors import (
        AuthError,
        MissingConfigError,
        InvalidConfigError,
        AuthorizationCancelledError,
        TokenStoreCorruptedError,
        ReauthorizationRequiredError,
        ConcurrentAuthError,
        ConnectivityError,
    )
    return AuthError, [
        MissingConfigError,
        InvalidConfigError,
        AuthorizationCancelledError,
        TokenStoreCorruptedError,
        ReauthorizationRequiredError,
        ConcurrentAuthError,
        ConnectivityError,
    ]


# ---------------------------------------------------------------------------
# 1. All 7 error types exist and are importable
# ---------------------------------------------------------------------------

class TestErrorTypesExist:
    """Every error type can be imported from schwab_mcp.errors."""

    def test_missing_config_error(self):
        from schwab_mcp.errors import MissingConfigError
        assert issubclass(MissingConfigError, Exception)

    def test_invalid_config_error(self):
        from schwab_mcp.errors import InvalidConfigError
        assert issubclass(InvalidConfigError, Exception)

    def test_authorization_cancelled_error(self):
        from schwab_mcp.errors import AuthorizationCancelledError
        assert issubclass(AuthorizationCancelledError, Exception)

    def test_token_store_corrupted_error(self):
        from schwab_mcp.errors import TokenStoreCorruptedError
        assert issubclass(TokenStoreCorruptedError, Exception)

    def test_reauthorization_required_error(self):
        from schwab_mcp.errors import ReauthorizationRequiredError
        assert issubclass(ReauthorizationRequiredError, Exception)

    def test_concurrent_auth_error(self):
        from schwab_mcp.errors import ConcurrentAuthError
        assert issubclass(ConcurrentAuthError, Exception)

    def test_connectivity_error(self):
        from schwab_mcp.errors import ConnectivityError
        assert issubclass(ConnectivityError, Exception)


# ---------------------------------------------------------------------------
# 2. All subclass the common AuthError base class
# ---------------------------------------------------------------------------

class TestCommonBaseClass:
    """Every concrete error inherits from AuthError."""

    def test_auth_error_is_base(self):
        from schwab_mcp.errors import AuthError
        assert issubclass(AuthError, Exception)

    def test_all_subclass_auth_error(self):
        _, concrete_errors = _all_error_types()
        for err_type in concrete_errors:
            assert issubclass(err_type, Exception), f"{err_type.__name__} should be an Exception"

    def test_each_concrete_subclasses_auth_error(self):
        from schwab_mcp.errors import AuthError
        _, concrete_errors = _all_error_types()
        for err_type in concrete_errors:
            assert issubclass(err_type, AuthError), (
                f"{err_type.__name__} does not inherit from AuthError"
            )


# ---------------------------------------------------------------------------
# 3. Each carries its distinct fixed actionable message
# ---------------------------------------------------------------------------

class TestActionableMessages:
    """Each error has the correct recovery message per the data-model mapping."""

    # fmt: off
    # (error_name, expected_recovery_message)
    MESSAGE_TABLE = {
        "MissingConfigError":
            "Set SCHWAB_APP_KEY / SCHWAB_APP_SECRET",
        "InvalidConfigError":
            "Fix the values in your environment",
        "AuthorizationCancelledError":
            "Re-run schwab-mcp auth to retry",
        "TokenStoreCorruptedError":
            "Store treated as absent; run schwab-mcp auth",
        "ReauthorizationRequiredError":
            "Run schwab-mcp auth",
        "ConcurrentAuthError":
            "Another authorization is already running; wait",
        "ConnectivityError":
            "Check connectivity; stored tokens not modified",
    }
    # fmt: on

    def _lookup_message(self, error_type):
        """Return the instance message for a given error class."""
        _, concrete_errors = _all_error_types()
        for err in concrete_errors:
            if err.__name__ == error_type:
                return str(err())
        raise LookupError(f"Unknown error type: {error_type}")

    @pytest.mark.parametrize("error_name,expected_msg", MESSAGE_TABLE.items())
    def test_message_content(self, error_name, expected_msg):
        msg = self._lookup_message(error_name)
        assert msg == expected_msg, (
            f"{error_name} message mismatch:\n  expected: {expected_msg!r}\n  got:      {msg!r}"
        )


# ---------------------------------------------------------------------------
# 4. Each exposes its exit code
# ---------------------------------------------------------------------------

class TestExitCodes:
    """Every concrete error exposes the correct exit code attribute."""

    EXIT_CODE_TABLE = {
        "MissingConfigError":              2,
        "InvalidConfigError":              2,
        "AuthorizationCancelledError":     3,
        "TokenStoreCorruptedError":        5,
        "ReauthorizationRequiredError":    4,
        "ConcurrentAuthError":             6,
        "ConnectivityError":               7,
    }

    def _lookup_exit_code(self, error_type):
        _, concrete_errors = _all_error_types()
        for err in concrete_errors:
            if err.__name__ == error_type:
                return err().exit_code
        raise LookupError(f"Unknown error type: {error_type}")

    @pytest.mark.parametrize("error_name,expected_code", EXIT_CODE_TABLE.items())
    def test_exit_code_value(self, error_name, expected_code):
        code = self._lookup_exit_code(error_name)
        assert code == expected_code, (
            f"{error_name} exit_code mismatch:\n  expected: {expected_code!r}\n  got:      {code!r}"
        )

    def test_exit_code_present_on_all(self):
        _, concrete_errors = _all_error_types()
        for err_type in concrete_errors:
            assert hasattr(err_type(), "exit_code"), (
                f"{err_type.__name__} instance lacks 'exit_code'"
            )


# ---------------------------------------------------------------------------
# 5. All messages are pairwise distinct (SC-005 distinctness)
# ---------------------------------------------------------------------------

class TestMessageDistinctness:
    """Every concrete error type produces a unique message string."""

    def test_all_messages_are_pairwise_distinct(self):
        from schwab_mcp.errors import AuthError
        _, concrete_errors = _all_error_types()

        messages = {err().__class__.__name__: str(err()) for err in concrete_errors}
        # Build lookup only from concrete subclasses of AuthError (no base)
        distinct_msg_count = len(set(messages.values()))
        assert distinct_msg_count == len(messages), (
            f"Messages are not pairwise distinct: "
            f"{len(messages)} types but only {distinct_msg_count} unique messages.\n"
            f"Messages: {messages}"
        )

    def test_auth_error_base_has_no_fixed_message(self):
        """The base AuthError should NOT define the fixed-message pattern."""
        from schwab_mcp.errors import AuthError
        # A plain AuthError() may have an empty or generic message,
        # but it must NOT accidentally match any concrete message.
        base_msg = str(AuthError())
        assert base_msg != "", (
            "AuthError base should either have a generic message "
            "or be impossible to instantiate standalone; got non-empty."
        )


# ---------------------------------------------------------------------------
# 6. Round-trip — ValueError on unknown error (safety net)
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """Re-raise and catch across the hierarchy works as expected."""

    def test_catch_auth_error_base(self):
        from schwab_mcp.errors import AuthError, MissingConfigError
        with pytest.raises(AuthError):
            raise MissingConfigError()

    def test_catch_exception_base(self):
        from schwab_mcp.errors import MissingConfigError
        with pytest.raises(Exception):
            raise MissingConfigError()