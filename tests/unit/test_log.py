"""
Failing unit tests for the redaction filter and auth event logging module.

Tests will fail at import time because src/schwab_mcp/log.py does not yet
exist (TDD red phase). Once the module is created, these tests validate:

- register_secret() / install_redaction_filter() / auth_event()
- Secret scrubbing via a logging Filter (FR-006)
- stderr-only emission with ISO-8601 UTC timestamps
- Event and outcome value restrictions (FR-014)
- Exact line format from contracts/events.md
"""

import logging
import re

import pytest

# ---------------------------------------------------------------------------
# Import the module under test — this WILL raise ModuleNotFoundError until
# src/schwab_mcp/log.py is created (TDD red phase).
# ---------------------------------------------------------------------------
from schwab_mcp.log import (
    auth_event,
    install_redaction_filter,
    register_secret,
)

# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------

ISO_8601_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z[+-]\d{2}:\d{2}"
)


ALLOWED_EVENTS = frozenset(
    {"auth_start", "auth_success", "auth_failure", "renewal_success", "renewal_failure"}
)

ALLOWED_OUTCOMES = {
    "auth_start": {"initiated"},
    "auth_success": {"ok"},
    "auth_failure": {"cancelled", "failed", "refused_concurrent"},
    "renewal_success": {"ok"},
    "renewal_failure": {"connectivity", "reauth_required"},
}


def make_log_record(msg: str, logger_name: str = "test") -> logging.LogRecord:
    """Build a synthetic LogRecord with the given message."""
    return logging.LogRecord(
        name=logger_name,
        level=logging.INFO,
        pathname=__file__,
        lineno=100,
        msg=msg,
        args=(),
        exc_info=None,
    )


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset global redaction state before every test.

    This fixture runs automatically. Subclasses of logging.Filter or a
    module-level set are reset so tests do not leak secrets across runs.
    """
    # We assume the module exposes a way to clear registered secrets;
    # if not, this fixture can be removed and tests become order-dependent.
    # For now we attempt a reset — if the module has no such function the
    # fixture will fail (acceptable during TDD).
    try:
        from schwab_mcp.log import clear_secrets  # fmt: skip
        clear_secrets()
    except (ImportError, AttributeError):
        pass


# ===================================================================
# Module existence & public API surface
# ===================================================================


class TestPublicAPI:
    """Verify the module exposes exactly the required public symbols."""

    def test_register_secret_exists(self):
        """register_secret is a callable function."""
        assert callable(register_secret)

    def test_install_redaction_filter_exists(self):
        """install_redaction_filter is a callable function."""
        assert callable(install_redaction_filter)

    def test_auth_event_exists(self):
        """auth_event is a callable function."""
        assert callable(auth_event)


# ===================================================================
# register_secret
# ===================================================================


class TestRegisterSecret:
    """register_secret() behaviour."""

    def test_register_secret_empty_string_raises(self):
        """Empty string secrets should be rejected."""
        with pytest.raises(ValueError, match="cannot be empty"):
            register_secret("")

    def test_register_secret_whitespace_only_raises(self):
        """Whitespace-only secrets should be rejected."""
        with pytest.raises(ValueError, match="cannot be empty"):
            register_secret("   ")

    def test_register_secret_none_raises(self):
        """None secrets should be rejected."""
        with pytest.raises(TypeError):
            register_secret(None)

    def test_secret_ids_are_stable(self):
        """Registering the same secret twice does not cause errors."""
        register_secret("some-token")
        register_secret("some-token")  # should not raise


# ===================================================================
# Redaction Filter (FR-006)
# ===================================================================


class TestRedactionFilter:
    """Verify the logging Filter scrubs all registered secret values."""

    # ------------------------------------------------------------------
    # Basic scrubbing
    # ------------------------------------------------------------------

    def test_scrubs_app_key(self):
        """App key is replaced with *** in log record messages."""
        app_key = "DEV_APP_KEY_12345"
        register_secret(app_key)
        flt = install_redaction_filter(logging.getLogger("test"))
        record = make_log_msg(app_key)
        assert not flt.filter(record)
        assert "***" in record.msg
        assert app_key not in record.msg

    def test_scrubs_app_secret(self):
        """App secret is replaced with ***."""
        secret = "super-secret-credential"
        register_secret(secret)
        flt = install_redaction_filter(logging.getLogger("test"))
        record = make_log_msg(secret)
        assert not flt.filter(record)
        assert "***" in record.msg

    def test_scrubs_access_token(self):
        """Access token is replaced with ***."""
        token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.mock-access"
        register_secret(token)
        flt = install_redaction_filter(logging.getLogger("test"))
        record = make_log_msg(token)
        assert not flt.filter(record)
        assert "***" in record.msg

    def test_scrubs_refresh_token(self):
        """Refresh token is replaced with ***."""
        token = "mock-refresh-token-abc123"
        register_secret(token)
        flt = install_redaction_filter(logging.getLogger("test"))
        record = make_log_msg(token)
        assert not flt.filter(record)
        assert "***" in record.msg

    def test_scrubs_id_token(self):
        """ID token is replaced with ***."""
        token = "mock-id-token-xyz789"
        register_secret(token)
        flt = install_redaction_filter(logging.getLogger("test"))
        record = make_log_msg(token)
        assert not flt.filter(record)
        assert "***" in record.msg

    def test_scrubs_authorization_code(self):
        """Authorization code is replaced with ***."""
        code = "auth-code-abc-def-ghi"
        register_secret(code)
        flt = install_redaction_filter(logging.getLogger("test"))
        record = make_log_msg(code)
        assert not flt.filter(record)
        assert "***" in record.msg

    # ------------------------------------------------------------------
    # Multiple secrets
    # ------------------------------------------------------------------

    def test_multiple_secrets_all_scrubbed(self):
        """Multiple registered secrets are all replaced in a single record."""
        app_key = "key-111"
        app_secret = "secret-222"
        token = "access-333"
        register_secret(app_key)
        register_secret(app_secret)
        register_secret(token)
        flt = install_redaction_filter(logging.getLogger("test"))
        msg = f"app_key={app_key}, app_secret={app_secret}, token={token}"
        record = make_log_msg(msg)
        assert not flt.filter(record)
        assert app_key not in record.msg
        assert app_secret not in record.msg
        assert token not in record.msg
        # Verify the message still has content (not entirely replaced)
        assert "app_key=" in record.msg
        assert "app_secret=" in record.msg

    def test_secret_in_the_middle_of_message(self):
        """Secrets embedded in longer text are still replaced."""
        secret = "my-secret-value"
        register_secret(secret)
        flt = install_redaction_filter(logging.getLogger("test"))
        msg = f"before {secret} after"
        record = make_log_msg(msg)
        assert not flt.filter(record)
        assert "***" in record.msg
        assert "before " in record.msg
        assert " after" in record.msg

    # ------------------------------------------------------------------
    # Substring safety
    # ------------------------------------------------------------------


    def test_secret_does_not_scrub_substrings(self):
        """A secret that is a substring of another string does not corrupt unrelated text."""
        register_secret("abc")
        flt = install_redaction_filter(logging.getLogger("test"))
        record = make_log_msg("some-abcde-text")
        assert not flt.filter(record)
        assert "***" in record.msg

    # ------------------------------------------------------------------
    # No secrets → no change
    # ------------------------------------------------------------------

    def test_no_secrets_leaves_message_unchanged(self):
        """A record without any registered secret passes through unmodified."""
        register_secret("some-token")
        flt = install_redaction_filter(logging.getLogger("test"))
        msg = "this message contains no secrets"
        record = make_log_msg(msg)
        assert flt.filter(record)
        assert record.msg == msg

    # ------------------------------------------------------------------
    # Install on multiple loggers
    # ------------------------------------------------------------------

    def test_install_on_root_logger(self):
        """Filter can be installed on the root logger."""
        flt = install_redaction_filter(logging.root)
        assert flt is not None
        # Clean up
        logging.root.removeFilter(flt)

    def test_install_on_schwabdev_logger(self):
        """Filter can be installed on the 'Schwabdev' logger (or any named logger)."""
        logger = logging.getLogger("Schwabdev")
        flt = install_redaction_filter(logger)
        assert flt is not None
        logger.removeFilter(flt)

    def test_install_returns_the_filter_instance(self):
        """install_redaction_filter returns the created filter so callers can
        remove it later if desired."""
        logger = logging.getLogger("test-return")
        flt = install_redaction_filter(logger)
        assert isinstance(flt, logging.Filter)
        logger.removeFilter(flt)

    def test_double_install_does_not_duplicate_filter(self):
        """Installing the filter twice on the same logger does not add duplicates."""
        logger = logging.getLogger("test-double")
        flt1 = install_redaction_filter(logger)
        flt2 = install_redaction_filter(logger)
        assert flt1 is flt2
        assert len(logger.filters) == 1
        logger.removeFilter(flt1)


# ===================================================================
# auth_event — stderr emission (FR-014)
# ===================================================================


class TestAuthEventStderr:
    """Auth events emit to stderr, never stdout."""

    def test_emits_to_stderr(self, capsys):
        """auth_event writes to stderr."""
        auth_event("auth_start", "initiated", detail="browser flow requested")
        captured = capsys.readouterr()
        assert captured.err, "Expected output on stderr"
        assert captured.out == "", "Expected nothing on stdout (MCP stdio channel)"

    def test_different_events_go_to_stderr(self, capsys):
        """Multiple different event types all write to stderr."""
        auth_event("auth_start", "initiated")
        auth_event("auth_success", "ok")
        captured = capsys.readouterr()
        assert captured.err
        assert captured.out == ""

    def test_stdout_remains_empty_after_many_events(self, capsys):
        """Even after many auth_event calls, stdout stays empty."""
        outcomes = {"auth_start": "initiated", "auth_success": "ok", "auth_failure": "cancelled", "renewal_success": "ok", "renewal_failure": "reauth_required"}
        for evt, outcome in outcomes.items():
            auth_event(evt, outcome)
        captured = capsys.readouterr()
        assert captured.out == ""


# ===================================================================
# auth_event — line format (contracts/events.md)
# ===================================================================


class TestAuthEventFormat:
    """auth_event line format matches contracts/events.md."""

    # The contract line format is:
    # <ISO-8601 UTC timestamp> auth_event=<event> outcome=<outcome> [detail=<fixed detail>]

    def test_line_starts_with_iso8601_timestamp(self, capsys):
        """The emitted line starts with an ISO-8601 UTC timestamp."""
        auth_event("auth_start", "initiated", detail="browser flow requested")
        line = capsys.readouterr().err.strip()
        timestamp_part = line.split(" auth_event=")[0]
        assert ISO_8601_UTC_RE.match(timestamp_part), (
            f"Timestamp '{timestamp_part}' does not match ISO-8601 UTC format"
        )

    def test_line_contains_auth_event_field(self, capsys):
        """The emitted line includes 'auth_event=<event>'."""
        auth_event("auth_success", "ok", detail="tokens stored")
        line = capsys.readouterr().err.strip()
        assert "auth_event=auth_success" in line

    def test_line_contains_outcome_field(self, capsys):
        """The emitted line includes 'outcome=<outcome>'."""
        auth_event("auth_failure", "cancelled", detail="run: schwab-mcp auth to retry")
        line = capsys.readouterr().err.strip()
        assert "outcome=cancelled" in line

    def test_line_without_detail(self, capsys):
        """When detail is None, the line omits the detail field."""
        auth_event("auth_start", "initiated")
        line = capsys.readouterr().err.strip()
        assert "detail=" not in line

    def test_line_with_detail(self, capsys):
        """When detail is provided, it appears at the end of the line."""
        detail = "browser flow requested"
        auth_event("auth_start", "initiated", detail=detail)
        line = capsys.readouterr().err.strip()
        assert line.endswith(f"detail={detail}")

    def test_exact_line_format_auth_start(self, capsys):
        """auth_start line matches example from events.md precisely in structure."""
        auth_event("auth_start", "initiated", detail="browser flow requested")
        line = capsys.readouterr().err.strip()
        # Match: <TS> auth_event=auth_start outcome=initiated detail=browser flow requested
        assert "auth_event=auth_start" in line
        assert "outcome=initiated" in line
        assert "detail=browser flow requested" in line

    def test_exact_line_format_auth_success(self, capsys):
        auth_event("auth_success", "ok", detail="tokens stored at ~/.schwab-mcp/tokens.db")
        line = capsys.readouterr().err.strip()
        assert "auth_event=auth_success" in line
        assert "outcome=ok" in line
        assert "detail=tokens stored at ~/.schwab-mcp/tokens.db" in line

    def test_exact_line_format_auth_failure(self, capsys):
        auth_event("auth_failure", "cancelled", detail="run: schwab-mcp auth to retry")
        line = capsys.readouterr().err.strip()
        assert "auth_event=auth_failure" in line
        assert "outcome=cancelled" in line
        assert "detail=run: schwab-mcp auth to retry" in line

    def test_exact_line_format_renewal_success(self, capsys):
        auth_event("renewal_success", "ok", detail="access token renewed")
        line = capsys.readouterr().err.strip()
        assert "auth_event=renewal_success" in line
        assert "outcome=ok" in line
        assert "detail=access token renewed" in line

    def test_exact_line_format_renewal_failure(self, capsys):
        auth_event("renewal_failure", "reauth_required", detail="run: schwab-mcp auth")
        line = capsys.readouterr().err.strip()
        assert "auth_event=renewal_failure" in line
        assert "outcome=reauth_required" in line
        assert "detail=run: schwab-mcp auth" in line

    def test_timestamp_is_utc_with_offset(self, capsys):
        """The timestamp ends with +00:00 (UTC offset)."""
        auth_event("auth_start", "initiated")
        line = capsys.readouterr().err.strip()
        ts = line.split(" ")[0]
        assert ts.endswith("+00:00"), f"Timestamp '{ts}' does not end with +00:00"

    def test_timestamp_contains_z(self, capsys):
        """The timestamp contains 'Z' before the offset, per ISO-8601."""
        auth_event("auth_start", "initiated")
        line = capsys.readouterr().err.strip()
        ts = line.split(" ")[0]
        assert "Z" in ts, f"Timestamp '{ts}' does not contain 'Z'"

    def test_newline_at_end(self, capsys):
        """Each event line ends with a newline."""
        auth_event("auth_start", "initiated")
        captured = capsys.readouterr()
        assert captured.err.endswith("\n")


# ===================================================================
# auth_event — event value validation (FR-014)
# ===================================================================


class TestAuthEventValidation:
    """auth_event enforces allowed event and outcome values."""

    @pytest.mark.parametrize("event", sorted(ALLOWED_EVENTS))
    def test_allowed_events_succeed(self, event, capsys):
        """Each allowed event emits a line without error."""
        outcome = next(iter(ALLOWED_OUTCOMES[event]))
        auth_event(event, outcome)
        assert capsys.readouterr().err

    @pytest.mark.parametrize(
        "invalid_event",
        [
            "unknown_event",
            "auth_bogus",
            "start",
            "log_in",
            "auth_Failure",
            "AuthStart",
            "",
            " ",
        ],
    )
    def test_disallowed_event_raises(self, invalid_event, capsys):
        """An event value not in the allowed set raises ValueError (FR-014)."""
        with pytest.raises(ValueError, match="event"):
            auth_event(invalid_event, "initiated")

    def test_case_sensitive_event(self, capsys):
        """Event values are case-sensitive; wrong case raises."""
        with pytest.raises(ValueError):
            auth_event("Auth_Start", "initiated")

    @pytest.mark.parametrize(
        "outcome",
        ["wrong", "okay", "cancelled_but_wrong", "refused", "no_init", ""],
    )
    def test_disallowed_outcome_for_event_raises(self, outcome, capsys):
        """An outcome not in the allowed set for a given event raises ValueError."""
        with pytest.raises(ValueError, match="outcome"):
            auth_event("auth_failure", outcome)


# ===================================================================
# auth_event — outcome validation per event type
# ===================================================================


class TestAuthEventOutcomePerEvent:
    """Outcome values are restricted per event type (contracts/events.md table)."""

    # auth_start → {initiated}
    def test_auth_start_accepts_initiated(self, capsys):
        auth_event("auth_start", "initiated")
        assert capsys.readouterr().err

    def test_auth_start_rejects_ok(self, capsys):
        with pytest.raises(ValueError):
            auth_event("auth_start", "ok")

    # auth_success → {ok}
    def test_auth_success_accepts_ok(self, capsys):
        auth_event("auth_success", "ok")
        assert capsys.readouterr().err

    def test_auth_success_rejects_cancelled(self, capsys):
        with pytest.raises(ValueError):
            auth_event("auth_success", "cancelled")

    # auth_failure → {cancelled, failed, refused_concurrent}
    @pytest.mark.parametrize("outcome", ["cancelled", "failed", "refused_concurrent"])
    def test_auth_failure_accepts(self, outcome, capsys):
        auth_event("auth_failure", outcome)
        assert capsys.readouterr().err

    def test_auth_failure_rejects_ok(self, capsys):
        with pytest.raises(ValueError):
            auth_event("auth_failure", "ok")

    # renewal_success → {ok}
    def test_renewal_success_accepts_ok(self, capsys):
        auth_event("renewal_success", "ok")
        assert capsys.readouterr().err

    def test_renewal_success_rejects_connectivity(self, capsys):
        with pytest.raises(ValueError):
            auth_event("renewal_success", "connectivity")

    # renewal_failure → {connectivity, reauth_required}
    @pytest.mark.parametrize("outcome", ["connectivity", "reauth_required"])
    def test_renewal_failure_accepts(self, outcome, capsys):
        auth_event("renewal_failure", outcome)
        assert capsys.readouterr().err

    def test_renewal_failure_rejects_ok(self, capsys):
        with pytest.raises(ValueError):
            auth_event("renewal_failure", "ok")


# ===================================================================
# auth_event — detail examples from events.md
# ===================================================================


class TestAuthEventDetailExamples:
    """The detail values from contracts/events.md must be accepted."""

    # Examples from events.md:
    # "browser flow requested"
    # "tokens stored at ~/.schwab-mcp/tokens.db"
    # "run: schwab-mcp auth to retry"
    # "access token renewed"
    # "run: schwab-mcp auth"

    def test_detail_browser_flow_requested(self, capsys):
        auth_event("auth_start", "initiated", detail="browser flow requested")
        assert "detail=browser flow requested" in capsys.readouterr().err

    def test_detail_tokens_stored(self, capsys):
        auth_event(
            "auth_success",
            "ok",
            detail="tokens stored at ~/.schwab-mcp/tokens.db",
        )
        assert "detail=tokens stored at ~/.schwab-mcp/tokens.db" in capsys.readouterr().err

    def test_detail_run_auth_to_retry(self, capsys):
        auth_event(
            "auth_failure",
            "cancelled",
            detail="run: schwab-mcp auth to retry",
        )
        assert "detail=run: schwab-mcp auth to retry" in capsys.readouterr().err

    def test_detail_access_token_renewed(self, capsys):
        auth_event("renewal_success", "ok", detail="access token renewed")
        assert "detail=access token renewed" in capsys.readouterr().err

    def test_detail_run_auth(self, capsys):
        auth_event("renewal_failure", "reauth_required", detail="run: schwab-mcp auth")
        assert "detail=run: schwab-mcp auth" in capsys.readouterr().err


# ===================================================================
# auth_event — secrets scrubbed from events (FR-006 defense-in-depth)
# ===================================================================


class TestAuthEventSecretFree:
    """auth_event output must be secret-free (FR-006 / SC-003)."""

    def test_secret_in_detail_is_scrubbed(self, capsys):
        """If a registered secret leaks into the detail field, it is replaced."""
        register_secret("my-secret-token")
        auth_event("auth_success", "ok", detail="token=my-secret-token")
        line = capsys.readouterr().err.strip()
        assert "my-secret-token" not in line
        assert "***" in line


# ===================================================================
# Helper (reusable)
# ===================================================================

def make_log_msg(text: str) -> logging.LogRecord:
    """Create a simple LogRecord whose message is *text*."""
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=100,
        msg=text,
        args=(),
        exc_info=None,
    )