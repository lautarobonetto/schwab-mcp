"""End-to-end leak sweep: zero credential/token material in any output (FR-006, SC-003).

Verifies that ``schwab-mcp auth`` and ``schwab-mcp serve`` produce zero
occurrences of registered secrets (app secret, access token, refresh token,
id token, authorization code) in stdout, stderr, and all log records. The
app key (client_id) is public by OAuth design and may appear ONLY inside
the displayed authorization URL, which must be usable as-is (amended
FR-006); see ``TestAuthUrlUsability``.

Also includes a **negative control** (Principle V) that confirms the
redaction filter actually transforms records that contain a secret.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from schwab_mcp.cli import main
from schwab_mcp.log import (
    _installed_filters,
    _RedactionFilter,
    auth_event,
    clear_secrets,
    register_secret,
)
from schwab_mcp.renewal import AuthHealth, RenewalOutcome

# ---------------------------------------------------------------------------
# Constants — the fake defaults that the test environment configures
# ---------------------------------------------------------------------------

TEST_APP_KEY = "TEST_APP_KEY_32CHARS__FILLER"
TEST_APP_SECRET = "TEST_APP_SECRET_32CHAR_FILLER"
FAKE_ACCESS_TOKEN = "fake-access-token"
FAKE_REFRESH_TOKEN = "fake-refresh-token"
FAKE_ID_TOKEN = "fake-id-token"
FAKE_AUTH_CODE = "auth-code-abc-def-ghi"

# Secret material that must NEVER appear in any output channel (FR-006).
# The app key (client_id) is deliberately NOT in this set: it is public by
# OAuth design and MUST be printed in full inside the displayed
# authorization URL so the URL is usable as-is (amended FR-006). Outside
# that URL it must still not appear.
SECRET_MATERIAL = frozenset({
    TEST_APP_SECRET,
    FAKE_ACCESS_TOKEN,
    FAKE_REFRESH_TOKEN,
    FAKE_ID_TOKEN,
    FAKE_AUTH_CODE,
})

AUTH_URL_MARKER = "api.schwabapi.com/v1/oauth/authorize"


def assert_app_key_only_in_auth_url(lines: list[str], where: str) -> None:
    """The app key may appear only inside the displayed authorization URL."""
    outside = "\n".join(ln for ln in lines if AUTH_URL_MARKER not in ln)
    assert TEST_APP_KEY not in outside, (
        f"App key leaked outside the authorization URL in {where}"
    )

# ---------------------------------------------------------------------------
# Fake schwabdev Client (mirrors the integration-test pattern)
# ---------------------------------------------------------------------------


class FakeSchwabdevClient:
    """Stubbed schwabdev Client for testing the auth flow without a network."""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        callback_url: str,
        tokens_db: str | Path,
        call_on_auth=None,
        open_browser_for_auth: bool = False,
        **kwargs: object,
    ) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.callback_url = callback_url
        self.tokens_db = str(tokens_db)
        self.call_on_auth = call_on_auth
        self.open_browser_for_auth = open_browser_for_auth
        self._token_store_written = False

    def linked_accounts(self) -> dict[str, object]:
        return {"accounts": [{"accountNumber": "12345678", "type": "MARGIN"}]}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_logging_state():
    """Clear registered secrets and remove any previously installed filters
    before every test so state does not leak between runs."""
    # Remove filters that were installed by a previous test run.
    for logger_name, flt in list(_installed_filters.items()):
        logger = logging.getLogger(logger_name)
        logger.removeFilter(flt)
    clear_secrets()


@pytest.fixture
def default_env(monkeypatch, tmp_path):
    """Set a clean environment with the default fake credentials and stub
    the schwabdev Client so auth doesn't make network calls."""
    monkeypatch.setenv("SCHWAB_APP_KEY", TEST_APP_KEY)
    monkeypatch.setenv("SCHWAB_APP_SECRET", TEST_APP_SECRET)
    monkeypatch.setenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1")
    monkeypatch.setenv("SCHWAB_TOKEN_DB", str(tmp_path / "tokens.db"))
    monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient)


# ---------------------------------------------------------------------------
# Capture helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def tracking_print(monkeypatch):
    """Monkeypatch ``builtins.print`` to capture all output into two
    lists (``captured_stdout``, ``captured_stderr``) that the test can
    inspect."""
    import sys as _sys

    captured_stdout: list[str] = []
    captured_stderr: list[str] = []

    def _print(*args, **kwargs):
        file = kwargs.get("file", logging.root)  # sentinel — not sys.stdout/stderr
        text = " ".join(str(a) for a in args)
        # If file is explicitly sys.stderr we treat it as stderr; everything
        # else (including default = sys.stdout) is stdout.
        if file is _sys.stderr:
            captured_stderr.append(text)
            return
        captured_stdout.append(text)

    monkeypatch.setattr("builtins.print", _print)
    return captured_stdout, captured_stderr


# ===================================================================
# Negative control: the filter actually transforms a record
# ===================================================================


class TestNegativeControl:
    """Principle V: prove that the redaction filter *can* detect secrets.

    Without this negative control, a passing leak sweep could mean the
    filter simply never fires — giving a false sense of security.  By
    showing the filter *does* fire on a known-secret record, we validate
    both the filter itself and the test's detection logic.
    """

    def test_filter_scrubs_registered_secret(self):
        """A LogRecord containing a registered secret is mutated by the
        filter — ``record.msg`` has the secret replaced with ``***``."""
        register_secret("mysecret")
        flt = _RedactionFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=100,
            msg="this contains mysecret inside it",
            args=(),
            exc_info=None,
        )
        result = flt.filter(record)
        # The filter returns False when it redacts (discarding the record
        # from the logging chain) and mutates record.msg in-place.
        assert result is False, (
            f"Expected filter to return False (redacted), got {result}"
        )
        assert record.msg == "this contains *** inside it", (
            f"Expected secret replaced with ***, got: {record.msg!r}"
        )
        assert record.args == (), "record.args must be cleared after redaction"

    def test_filter_passes_clean_record(self):
        """A LogRecord without any registered secret passes through unchanged,
        returning True (logged normally)."""
        register_secret("some-other-secret")
        flt = _RedactionFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=100,
            msg="this message has no secrets",
            args=(),
            exc_info=None,
        )
        result = flt.filter(record)
        assert result is True, (
            f"Expected filter to return True (no redaction), got {result}"
        )
        assert record.msg == "this message has no secrets"

    def test_multiple_secrets_all_scrubbed(self):
        """Multiple registered secrets are all replaced in a single record."""
        register_secret("first")
        register_secret("second")
        register_secret("third")
        flt = _RedactionFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=100,
            msg="first and second and third present",
            args=(),
            exc_info=None,
        )
        result = flt.filter(record)
        assert result is False
        assert record.msg == "*** and *** and *** present"


# ===================================================================
# Auth subcommand — output leak sweep
# ===================================================================


class TestAuthNoSecretsInOutput:
    """End-to-end capture of all ``schwab-mcp auth`` output channels
    (stdout, stderr, log records) — zero occurrences of any secret."""

    def test_auth_stdout_and_stderr_have_no_secrets(
        self, default_env, monkeypatch, tmp_path, tracking_print,
    ):
        """Combined stdout+stderr from ``main(["auth"])`` must not contain
        any registered secret; the app key may appear only inside the
        displayed authorization URL."""
        captured_stdout, captured_stderr = tracking_print
        monkeypatch.setattr("webbrowser.open", lambda url: True)

        with pytest.raises(SystemExit):
            main(["auth"])

        all_output = "\n".join(captured_stdout + captured_stderr)

        for secret in SECRET_MATERIAL:
            assert secret not in all_output, (
                f"Secret {secret!r} leaked into auth output"
            )
        assert_app_key_only_in_auth_url(
            captured_stdout + captured_stderr, "auth stdout/stderr"
        )

    def test_auth_log_records_are_secret_free(
        self, default_env, monkeypatch, tmp_path, caplog,
    ):
        """All log records emitted during auth must be free of secrets."""
        caplog.set_level(logging.DEBUG)
        monkeypatch.setattr("webbrowser.open", lambda url: True)

        with pytest.raises(SystemExit):
            main(["auth"])

        for record in caplog.records:
            msg = record.getMessage()
            # The authorization URL is never logged (only printed), so the
            # app key must not appear in ANY log record either.
            for secret in [*SECRET_MATERIAL, TEST_APP_KEY]:
                assert secret not in msg, (
                    f"Secret {secret!r} leaked into log record: {msg!r}"
                )

    def test_auth_stdout_alone_has_no_secrets(
        self, default_env, monkeypatch, tmp_path,
    ):
        """The stdout stream (used by MCP stdio transport) must not contain
        any secrets; the app key may appear only inside the displayed
        authorization URL."""
        captured: list[str] = []

        def capture_print(*args, **kwargs):
            captured.extend(str(a) for a in args)

        monkeypatch.setattr("builtins.print", capture_print)
        monkeypatch.setattr("webbrowser.open", lambda url: True)

        with pytest.raises(SystemExit):
            main(["auth"])

        stdout_text = " ".join(captured)
        for secret in SECRET_MATERIAL:
            assert secret not in stdout_text, (
                f"Secret {secret!r} leaked into stdout"
            )
        assert_app_key_only_in_auth_url(captured, "auth stdout")


# ===================================================================
# Serve subcommand — output leak sweep
# ===================================================================


class TestServeNoSecretsInOutput:
    """End-to-end capture of ``schwab-mcp serve`` output (stderr + all log
    records).  The serve command will fail early because the token store is
    absent — we capture whatever was emitted before/during the failure."""

    def test_serve_stderr_has_no_secrets(
        self, default_env, monkeypatch, tmp_path, tracking_print,
    ):
        """stderr emitted by ``main(["serve"])`` must not contain any
        registered secret, even on the early-exit path."""
        captured_stdout, captured_stderr = tracking_print

        with pytest.raises(SystemExit):
            main(["serve"])

        stderr_text = "\n".join(captured_stderr)
        # serve never prints the authorization URL, so the app key must be
        # fully absent from its stderr.
        for secret in [*SECRET_MATERIAL, TEST_APP_KEY]:
            assert secret not in stderr_text, (
                f"Secret {secret!r} leaked into serve stderr"
            )

    def test_serve_log_records_are_secret_free(
        self, default_env, monkeypatch, tmp_path, caplog,
    ):
        """All log records emitted during serve must be free of secrets."""
        caplog.set_level(logging.DEBUG)

        with pytest.raises(SystemExit):
            main(["serve"])

        for record in caplog.records:
            msg = record.getMessage()
            for secret in [*SECRET_MATERIAL, TEST_APP_KEY]:
                assert secret not in msg, (
                    f"Secret {secret!r} leaked into serve log record: {msg!r}"
                )


# ===================================================================
# Auth + serve combined — output leak sweep
# ===================================================================


class TestCombinedOutputNoSecrets:
    """Run both subcommands in the same test and check no secrets appear
    in any output across both runs."""

    def test_both_subcommands_produce_no_secrets(
        self, default_env, monkeypatch, tmp_path, tracking_print,
    ):
        """Running both auth and serve in sequence produces no secret leaks."""
        captured_stdout, captured_stderr = tracking_print
        monkeypatch.setattr("webbrowser.open", lambda url: True)

        # Run auth
        with pytest.raises(SystemExit):
            main(["auth"])

        # Run serve
        with pytest.raises(SystemExit):
            main(["serve"])

        all_output = "\n".join(
            f"[stdout] {line}" for line in captured_stdout
        ) + "\n" + "\n".join(
            f"[stderr] {line}" for line in captured_stderr
        )

        for secret in SECRET_MATERIAL:
            assert secret not in all_output, (
                f"Secret {secret!r} leaked into combined output"
            )
        assert_app_key_only_in_auth_url(
            captured_stdout + captured_stderr, "combined output"
        )


# ===================================================================
# Authorization URL usability (amended FR-006)
# ===================================================================


class TestAuthUrlUsability:
    """Amended FR-006: the authorization URL displayed during ``auth`` MUST
    contain the client_id (app key) in full — it is public by OAuth design
    and the URL must be usable as-is (copy/paste into any browser, including
    a private window). The app secret, tokens, and authorization codes stay
    redacted everywhere (non-negotiable).
    """

    def test_printed_auth_url_contains_client_id_and_redirect_uri(
        self, default_env, monkeypatch, tracking_print,
    ):
        """The URL printed to stdout is the real authorization URL: real
        client_id, real redirect_uri, and no ``***`` placeholder inside it."""
        captured_stdout, _ = tracking_print
        monkeypatch.setattr("webbrowser.open", lambda url: True)

        with pytest.raises(SystemExit):
            main(["auth"])

        all_output = "\n".join(captured_stdout)
        expected_prefix = (
            "https://api.schwabapi.com/v1/oauth/authorize"
            f"?client_id={TEST_APP_KEY}&redirect_uri="
        )
        assert expected_prefix in all_output, (
            f"Printed authorization URL is not usable as-is; got stdout:\n{all_output}"
        )
        assert "client_id=***" not in all_output, (
            "client_id must not be redacted in the displayed authorization URL"
        )

    def test_browser_opens_the_same_url_that_is_printed(
        self, default_env, monkeypatch, tracking_print,
    ):
        """The URL handed to the browser and the URL printed to stdout are
        identical — the owner can always copy the printed one instead."""
        opened: dict[str, str] = {}
        captured_stdout, _ = tracking_print

        def fake_open(url: str) -> bool:
            opened["url"] = url
            return True

        monkeypatch.setattr("webbrowser.open", fake_open)

        with pytest.raises(SystemExit):
            main(["auth"])

        printed_urls = [
            ln.strip() for ln in captured_stdout if AUTH_URL_MARKER in ln
        ]
        assert printed_urls, "authorization URL was not printed to stdout"
        assert opened["url"] == printed_urls[0], (
            f"Browser URL {opened['url']!r} differs from printed URL "
            f"{printed_urls[0]!r}"
        )


# ===================================================================
# Renewal JSON output — zero secrets in serialised payloads (FR-004, SC-005)
# ===================================================================


class TestRenewalOutcomeJsonNoSecrets:
    """``RenewalOutcome.to_json()`` and ``AuthHealth.to_json()`` serialise
    to JSON that contains zero credential/token/authorization-URL material
    (FR-004, SC-005).

    These types carry only classification fields (outcome, state, etc.)
    and timing metadata — never raw secrets.  Registering secrets and
    inspecting the output confirms they do not leak.
    """

    def test_renewal_outcome_json_has_no_secrets(self):
        """All four ``RenewalOutcome`` variants produce JSON free of any
        registered secret."""
        clear_secrets()
        register_secret(FAKE_ACCESS_TOKEN)
        register_secret(FAKE_REFRESH_TOKEN)
        register_secret(TEST_APP_SECRET)
        register_secret(FAKE_ID_TOKEN)
        register_secret(FAKE_AUTH_CODE)

        outcomes = [
            RenewalOutcome(
                outcome="renewed",
                expires_in_seconds=1800,
                retryable=False,
                detail="access_renewed",
            ),
            RenewalOutcome(
                outcome="not_needed",
                expires_in_seconds=3600,
                retryable=False,
                detail="still_valid",
            ),
            RenewalOutcome(
                outcome="transient_failure",
                expires_in_seconds=None,
                retryable=True,
                detail="provider_unreachable",
            ),
            RenewalOutcome(
                outcome="reauth_required",
                expires_in_seconds=None,
                retryable=False,
                detail="refresh_rejected",
            ),
        ]
        for outcome in outcomes:
            json_text = outcome.to_json()
            for secret in SECRET_MATERIAL:
                assert secret not in json_text, (
                    f"Secret {secret!r} leaked into RenewalOutcome JSON: "
                    f"{json_text}"
                )

    def test_auth_health_json_has_no_secrets(self):
        """All ``AuthHealth`` state variants produce JSON free of any
        registered secret."""
        clear_secrets()
        register_secret(FAKE_ACCESS_TOKEN)
        register_secret(FAKE_REFRESH_TOKEN)
        register_secret(TEST_APP_SECRET)
        register_secret(FAKE_ID_TOKEN)
        register_secret(FAKE_AUTH_CODE)

        states = [
            AuthHealth(
                state="valid",
                access_expires_in_seconds=1800,
                refresh_expires_in_seconds=600000,
            ),
            AuthHealth(
                state="reauth_required",
                access_expires_in_seconds=None,
                refresh_expires_in_seconds=None,
            ),
            AuthHealth(
                state="store_absent",
                access_expires_in_seconds=None,
                refresh_expires_in_seconds=None,
            ),
            AuthHealth(
                state="store_corrupted",
                access_expires_in_seconds=None,
                refresh_expires_in_seconds=None,
            ),
        ]
        for health in states:
            json_text = health.to_json()
            for secret in SECRET_MATERIAL:
                assert secret not in json_text, (
                    f"Secret {secret!r} leaked into AuthHealth JSON: "
                    f"{json_text}"
                )


# ===================================================================
# Renewal event lines — zero secrets in auth_event output (FR-004, SC-005)
# ===================================================================


class TestRenewalEventLinesNoSecrets:
    """``auth_event()`` lines for ``renew_*`` events
    (``renew_start``, ``renewal_success``, ``renewal_failure``) must have
    all secret material redacted from the ``detail`` field before the line
    reaches stderr (FR-004, SC-005).

    The redaction is defence-in-depth: event consumers (parsers, logs)
    should never encounter raw credentials even if the caller accidentally
    includes them.
    """

    def test_renew_start_event_redacts_secrets(self, capsys):
        """``renew_start`` event with secret-bearing ``detail`` text gets
        secrets replaced with ``***``."""
        clear_secrets()
        register_secret(FAKE_ACCESS_TOKEN)
        register_secret(FAKE_REFRESH_TOKEN)

        auth_event(
            "renew_start", "initiated",
            detail=f"token={FAKE_ACCESS_TOKEN}",
        )
        captured = capsys.readouterr()
        assert FAKE_ACCESS_TOKEN not in captured.err, (
            "Access token leaked in renew_start stderr"
        )
        assert "***" in captured.err, (
            "Expected redacted output containing *** in stderr, "
            f"got: {captured.err!r}"
        )

    def test_renewal_success_event_redacts_secrets(self, capsys):
        """``renewal_success`` event with secret-bearing ``detail`` text
        gets secrets replaced with ``***``."""
        clear_secrets()
        register_secret(FAKE_REFRESH_TOKEN)
        register_secret(FAKE_ACCESS_TOKEN)

        auth_event(
            "renewal_success", "ok",
            detail=f"refreshed token={FAKE_REFRESH_TOKEN}",
        )
        captured = capsys.readouterr()
        assert FAKE_REFRESH_TOKEN not in captured.err, (
            "Refresh token leaked in renewal_success stderr"
        )
        assert "***" in captured.err, (
            "Expected redacted output containing *** in stderr, "
            f"got: {captured.err!r}"
        )

    def test_renewal_failure_event_redacts_secrets(self, capsys):
        """``renewal_failure`` event with secret-bearing ``detail`` text
        gets secrets replaced with ``***``."""
        clear_secrets()
        register_secret(FAKE_ACCESS_TOKEN)
        register_secret(FAKE_AUTH_CODE)

        auth_event(
            "renewal_failure", "reauth_required",
            detail=f"auth_code={FAKE_AUTH_CODE} reason=expired",
        )
        captured = capsys.readouterr()
        assert FAKE_AUTH_CODE not in captured.err, (
            "Auth code leaked in renewal_failure stderr"
        )
        assert "***" in captured.err, (
            "Expected redacted output containing *** in stderr, "
            f"got: {captured.err!r}"
        )


# ===================================================================
# Positions tool — zero secrets in all outcome forms (FR-008, SC-005)
# ===================================================================


class TestPositionsToolNoSecrets:
    """All five outcome forms of ``PositionsResult`` produce JSON that
    contains zero registered secrets and no raw account numbers (FR-008,
    SC-005).

    Covers:
    - ``ok`` with positions (detail ``data_received``)
    - ``ok`` with no positions (detail ``no_positions``)
    - ``partial_failure`` with ``accounts_failed``
    - ``transient_failure`` (``retryable=True``)
    - ``reauth_required``
    """

    # ------------------------------------------------------------------
    # Secrets sweep for each outcome form
    # ------------------------------------------------------------------

    def test_ok_with_positions_has_no_secrets(self) -> None:
        """``ok`` outcome with positions → JSON contains zero secrets."""
        from schwab_mcp.positions import PositionEntry, PositionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        entry = PositionEntry(
            account_hash="hash123",
            symbol="SPY",
            instrument_type="EQUITY",
            description="SPDR S&P 500 ETF Trust",
            quantity=10.0,
            average_price=580.25,
            market_value=5910.0,
            unrealized_pl=107.5,
            price_timestamp="2026-10-20T14:03:11+00:00",
        )
        result = PositionsResult(
            outcome="ok",
            positions=[entry],
            detail="data_received",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
        )
        json_text = result.model_dump_json(exclude_none=True)
        for secret in SECRET_MATERIAL:
            assert secret not in json_text, (
                f"Secret {secret!r} leaked into ok-with-positions JSON"
            )

    def test_ok_empty_has_no_secrets(self) -> None:
        """``ok`` outcome with empty positions → JSON contains zero secrets."""
        from schwab_mcp.positions import PositionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        result = PositionsResult(
            outcome="ok",
            positions=[],
            detail="no_positions",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
        )
        json_text = result.model_dump_json(exclude_none=True)
        for secret in SECRET_MATERIAL:
            assert secret not in json_text, (
                f"Secret {secret!r} leaked into ok-empty JSON"
            )

    def test_partial_failure_has_no_secrets(self) -> None:
        """``partial_failure`` with ``accounts_failed`` → JSON zero secrets."""
        from schwab_mcp.positions import PositionEntry, PositionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        entry = PositionEntry(
            account_hash="hash123",
            symbol="SPY",
            instrument_type="EQUITY",
            description="Test",
            quantity=10.0,
            average_price=100.0,
            market_value=1000.0,
            unrealized_pl=0.0,
            price_timestamp="2026-10-20T14:03:11+00:00",
        )
        result = PositionsResult(
            outcome="partial_failure",
            positions=[entry],
            detail="account_failed",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
            accounts_failed=[
                {"account_hash": "hash789", "detail": "provider_error"},
            ],
        )
        json_text = result.model_dump_json(exclude_none=True)
        for secret in SECRET_MATERIAL:
            assert secret not in json_text, (
                f"Secret {secret!r} leaked into partial_failure JSON"
            )

    def test_transient_failure_has_no_secrets(self) -> None:
        """``transient_failure`` → JSON contains zero secrets."""
        from schwab_mcp.positions import PositionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        result = PositionsResult(
            outcome="transient_failure",
            positions=[],
            detail="provider_unreachable",
            retryable=True,
            retrieved_at="2026-10-20T14:03:11+00:00",
        )
        json_text = result.model_dump_json(exclude_none=True)
        for secret in SECRET_MATERIAL:
            assert secret not in json_text, (
                f"Secret {secret!r} leaked into transient_failure JSON"
            )

    def test_reauth_required_has_no_secrets(self) -> None:
        """``reauth_required`` → JSON contains zero secrets."""
        from schwab_mcp.positions import PositionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        result = PositionsResult(
            outcome="reauth_required",
            positions=[],
            detail="reauth_needed",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
        )
        json_text = result.model_dump_json(exclude_none=True)
        for secret in SECRET_MATERIAL:
            assert secret not in json_text, (
                f"Secret {secret!r} leaked into reauth_required JSON"
            )

    # ------------------------------------------------------------------
    # Raw account number sweep (FR-008)
    # ------------------------------------------------------------------

    def test_ok_with_positions_no_raw_account_number(self) -> None:
        """The ``ok`` outcome JSON contains no raw account number
        (only opaque ``account_hash``)."""
        from schwab_mcp.positions import PositionEntry, PositionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        entry = PositionEntry(
            account_hash="hash123",
            symbol="SPY",
            instrument_type="EQUITY",
            description="Test",
            quantity=10.0,
            average_price=100.0,
            market_value=1000.0,
            unrealized_pl=0.0,
            price_timestamp="2026-10-20T14:03:11+00:00",
        )
        result = PositionsResult(
            outcome="ok",
            positions=[entry],
            detail="data_received",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
        )
        json_text = result.model_dump_json(exclude_none=True)
        assert "10000001" not in json_text, (
            "Raw account number leaked in ok-with-positions JSON"
        )
        assert "12345678" not in json_text, (
            "Raw account number leaked in ok-with-positions JSON"
        )

    def test_partial_failure_no_raw_account_number(self) -> None:
        """The ``partial_failure`` JSON contains no raw account number."""
        from schwab_mcp.positions import PositionEntry, PositionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        entry = PositionEntry(
            account_hash="hash123",
            symbol="SPY",
            instrument_type="EQUITY",
            description="Test",
            quantity=10.0,
            average_price=100.0,
            market_value=1000.0,
            unrealized_pl=0.0,
            price_timestamp="2026-10-20T14:03:11+00:00",
        )
        result = PositionsResult(
            outcome="partial_failure",
            positions=[entry],
            detail="account_failed",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
            accounts_failed=[
                {"account_hash": "hash789", "detail": "provider_error"},
            ],
        )
        json_text = result.model_dump_json(exclude_none=True)
        assert "10000001" not in json_text, (
            "Raw account number leaked in partial_failure JSON"
        )
        assert "12345678" not in json_text, (
            "Raw account number leaked in partial_failure JSON"
        )


# ===================================================================
# Transactions tool — zero secrets in all outcome forms (FR-006, SC-003)
# ===================================================================


class TestTransactionsToolNoSecrets:
    """All outcome forms of ``TransactionsResult`` produce JSON that
    contains zero registered secrets and no raw account numbers (FR-006,
    SC-003).

    Covers:
    - ``ok`` with movements (detail ``history_retrieved``)
    - ``ok`` with no movements (detail ``no_movements``)
    - ``ok`` with no movements for a filtered instrument
    - ``partial_failure`` with ``accounts_failed``
    - ``transient_failure`` (``retryable=True``)
    - ``reauth_required``
    - Extended movements with provider passthrough data
    """

    # ------------------------------------------------------------------
    # Secrets sweep for each outcome form
    # ------------------------------------------------------------------

    def test_ok_with_movements_has_no_secrets(self) -> None:
        """``ok`` outcome with movements → JSON contains zero secrets."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        entry = MovementEntry(
            account_hash="hash123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Bought 100 SPY @ 580.25",
            amount=58025.0,
            currency="USD",
            symbol="SPY",
            instrument_type="EQUITY",
        )
        result = TransactionsResult(
            outcome="ok",
            detail="history_retrieved",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
            total_count=1,
            movements=[entry],
            returned=1,
            has_more=False,
            next_offset=None,
            offset_echo=0,
        )
        json_text = result.model_dump_json(exclude_none=True)
        for secret in SECRET_MATERIAL:
            assert secret not in json_text, (
                f"Secret {secret!r} leaked into ok-with-movements JSON"
            )

    def test_ok_empty_has_no_secrets(self) -> None:
        """``ok`` outcome with empty movements (no_movements) → JSON zero secrets."""
        from schwab_mcp.transactions import TransactionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        result = TransactionsResult(
            outcome="ok",
            detail="no_movements",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
            total_count=0,
            movements=[],
            returned=0,
            has_more=False,
            next_offset=None,
            offset_echo=0,
        )
        json_text = result.model_dump_json(exclude_none=True)
        for secret in SECRET_MATERIAL:
            assert secret not in json_text, (
                f"Secret {secret!r} leaked into ok-empty JSON"
            )

    def test_ok_empty_for_instrument_has_no_secrets(self) -> None:
        """``ok`` outcome with no_movements_for_instrument → JSON zero secrets."""
        from schwab_mcp.transactions import TransactionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        result = TransactionsResult(
            outcome="ok",
            detail="no_movements_for_instrument",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
            total_count=0,
            movements=[],
            returned=0,
            has_more=False,
            next_offset=None,
            offset_echo=0,
        )
        json_text = result.model_dump_json(exclude_none=True)
        for secret in SECRET_MATERIAL:
            assert secret not in json_text, (
                f"Secret {secret!r} leaked into ok-empty-for-instrument JSON"
            )

    def test_partial_failure_has_no_secrets(self) -> None:
        """``partial_failure`` with ``accounts_failed`` → JSON zero secrets."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        entry = MovementEntry(
            account_hash="hash123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Bought 100 SPY @ 580.25",
            amount=58025.0,
            currency="USD",
            symbol="SPY",
            instrument_type="EQUITY",
        )
        result = TransactionsResult(
            outcome="partial_failure",
            detail="account_failed",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
            movements=[entry],
            total_count=1,
            returned=1,
            has_more=False,
            next_offset=None,
            offset_echo=0,
            accounts_failed=[
                {"account_hash": "hash789", "detail": "provider_error"},
            ],
        )
        json_text = result.model_dump_json(exclude_none=True)
        for secret in SECRET_MATERIAL:
            assert secret not in json_text, (
                f"Secret {secret!r} leaked into partial_failure JSON"
            )

    def test_transient_failure_has_no_secrets(self) -> None:
        """``transient_failure`` → JSON contains zero secrets."""
        from schwab_mcp.transactions import TransactionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        result = TransactionsResult(
            outcome="transient_failure",
            detail="provider_unreachable",
            retryable=True,
            retrieved_at="2026-10-20T14:03:11+00:00",
        )
        json_text = result.model_dump_json(exclude_none=True)
        for secret in SECRET_MATERIAL:
            assert secret not in json_text, (
                f"Secret {secret!r} leaked into transient_failure JSON"
            )

    def test_reauth_required_has_no_secrets(self) -> None:
        """``reauth_required`` → JSON contains zero secrets."""
        from schwab_mcp.transactions import TransactionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        result = TransactionsResult(
            outcome="reauth_required",
            detail="reauth_needed",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
        )
        json_text = result.model_dump_json(exclude_none=True)
        for secret in SECRET_MATERIAL:
            assert secret not in json_text, (
                f"Secret {secret!r} leaked into reauth_required JSON"
            )

    def test_ok_with_extended_movements_has_no_secrets(self) -> None:
        """``ok`` outcome with extended movements (provider passthrough) →
        JSON contains zero secrets even with provider data in fields."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        entry = MovementEntry(
            account_hash="hash123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Bought 100 SPY @ 580.25",
            amount=58025.0,
            currency="USD",
            symbol="SPY",
            instrument_type="EQUITY",
            extended={
                "type": "TRADE",
                "description": "Bought 100 SPY @ 580.25",
                "fees": 1.50,
                "commission": 0.50,
                "netAmount": 58025.0,
                "settlementDate": "2026-10-22",
                "transferItems": None,
                "activityId": "98765",
            },
        )
        result = TransactionsResult(
            outcome="ok",
            detail="history_retrieved",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
            total_count=1,
            movements=[entry],
            returned=1,
            has_more=False,
            next_offset=None,
            offset_echo=0,
        )
        json_text = result.model_dump_json(exclude_none=True)
        for secret in SECRET_MATERIAL:
            assert secret not in json_text, (
                f"Secret {secret!r} leaked into extended-movements JSON"
            )

    # ------------------------------------------------------------------
    # Raw account number sweep (FR-006)
    # ------------------------------------------------------------------

    def test_ok_with_movements_no_raw_account_number(self) -> None:
        """The ``ok`` outcome JSON contains no raw account number
        (only opaque ``account_hash``)."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        entry = MovementEntry(
            account_hash="hash123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Test",
            amount=100.0,
            currency="USD",
        )
        result = TransactionsResult(
            outcome="ok",
            detail="history_retrieved",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
            total_count=1,
            movements=[entry],
            returned=1,
            has_more=False,
            next_offset=None,
            offset_echo=0,
        )
        json_text = result.model_dump_json(exclude_none=True)
        assert "10000001" not in json_text, (
            "Raw account number leaked in ok-with-movements JSON"
        )
        assert "12345678" not in json_text, (
            "Raw account number leaked in ok-with-movements JSON"
        )

    def test_partial_failure_no_raw_account_number(self) -> None:
        """The ``partial_failure`` JSON contains no raw account number."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

        entry = MovementEntry(
            account_hash="hash123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Test",
            amount=100.0,
            currency="USD",
        )
        result = TransactionsResult(
            outcome="partial_failure",
            detail="account_failed",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
            movements=[entry],
            total_count=1,
            returned=1,
            has_more=False,
            next_offset=None,
            offset_echo=0,
            accounts_failed=[
                {"account_hash": "hash789", "detail": "provider_error"},
            ],
        )
        json_text = result.model_dump_json(exclude_none=True)
        assert "10000001" not in json_text, (
            "Raw account number leaked in partial_failure JSON"
        )
        assert "12345678" not in json_text, (
            "Raw account number leaked in partial_failure JSON"
        )


# ===================================================================
# Transactions events — zero secrets in auth_event output (FR-006, SC-003)
# ===================================================================


class TestTransactionsEventLinesNoSecrets:
    """``auth_event()`` lines for transaction query events
    (``transactions_query_start``, ``transactions_query_success``,
    ``transactions_query_failure``) must have all secret material redacted
    from the ``detail`` field before the line reaches stderr (FR-006,
    SC-003).

    The redaction is defence-in-depth: event consumers (parsers, logs)
    should never encounter raw credentials even if the caller accidentally
    includes them.
    """

    def test_transactions_query_start_event_redacts_secrets(self, capsys):
        """``transactions_query_start`` event with secret-bearing ``detail``
        text gets secrets replaced with ``***``."""
        clear_secrets()
        register_secret(FAKE_ACCESS_TOKEN)
        register_secret(FAKE_REFRESH_TOKEN)

        auth_event(
            "transactions_query_start", "initiated",
            detail=f"token={FAKE_ACCESS_TOKEN}",
        )
        captured = capsys.readouterr()
        assert FAKE_ACCESS_TOKEN not in captured.err, (
            "Access token leaked in transactions_query_start stderr"
        )
        assert "***" in captured.err, (
            "Expected redacted output containing *** in stderr, "
            f"got: {captured.err!r}"
        )

    def test_transactions_query_success_event_redacts_secrets(self, capsys):
        """``transactions_query_success`` event with secret-bearing ``detail``
        text gets secrets replaced with ``***``."""
        clear_secrets()
        register_secret(FAKE_ACCESS_TOKEN)
        register_secret(FAKE_REFRESH_TOKEN)

        auth_event(
            "transactions_query_success", "ok",
            detail=f"refreshed token={FAKE_REFRESH_TOKEN}",
        )
        captured = capsys.readouterr()
        assert FAKE_REFRESH_TOKEN not in captured.err, (
            "Refresh token leaked in transactions_query_success stderr"
        )
        assert "***" in captured.err, (
            "Expected redacted output containing *** in stderr, "
            f"got: {captured.err!r}"
        )

    def test_transactions_query_failure_event_redacts_secrets(self, capsys):
        """``transactions_query_failure`` event with secret-bearing ``detail``
        text gets secrets replaced with ``***``."""
        clear_secrets()
        register_secret(FAKE_ACCESS_TOKEN)
        register_secret(FAKE_AUTH_CODE)

        auth_event(
            "transactions_query_failure", "validation",
            detail=f"auth_code={FAKE_AUTH_CODE} reason=invalid",
        )
        captured = capsys.readouterr()
        assert FAKE_AUTH_CODE not in captured.err, (
            "Auth code leaked in transactions_query_failure stderr"
        )
        assert "***" in captured.err, (
            "Expected redacted output containing *** in stderr, "
            f"got: {captured.err!r}"
        )

# =============================================================================
# get_quotes tool (feature 010) — FR-010 credential safety
# =============================================================================


class TestQuotesToolNoSecrets:
    """Every result form of ``get_quotes`` — and its audit events — carry
    zero registered secrets and no account identifiers (FR-010).

    Covers: ``ok`` curated, ``ok`` extended (raw provider channel),
    ``quote_unavailable``, ``validation_error``, ``provider_unreachable``,
    ``reauth_needed``, plus the real ``quotes_query_*`` event lines.
    """

    def _register(self) -> None:
        clear_secrets()
        for secret in SECRET_MATERIAL:
            register_secret(secret)

    def _client(self, **kwargs):
        from tests.unit.fixtures.quotes_payloads import EQUITY_QUOTE_ENTRY
        from tests.unit.helpers import FakeQuotesClient

        kwargs.setdefault("quotes_payload", {"AAPL": EQUITY_QUOTE_ENTRY})
        return FakeQuotesClient(**kwargs)

    def _assert_clean(self, result: dict, where: str) -> None:
        import json as _json

        text = _json.dumps(result)
        for secret in SECRET_MATERIAL:
            assert secret not in text, f"Secret {secret!r} leaked into {where}"
        for marker in ("accountnumber", "account_number", "account_hash"):
            assert marker not in text.lower(), (
                f"Account identifier {marker!r} leaked into {where}"
            )

    def test_ok_curated_has_no_secrets(self) -> None:
        from schwab_mcp.quotes import get_quotes

        self._register()
        result = get_quotes(self._client(), "AAPL")
        assert result["outcome"] == "ok"
        self._assert_clean(result, "ok curated quotes JSON")

    def test_ok_extended_has_no_secrets(self) -> None:
        from tests.unit.fixtures.quotes_payloads import EQUITY_ALL_ENTRY

        from schwab_mcp.quotes import get_quotes

        self._register()
        client = self._client(quotes_payload={"AAPL": EQUITY_ALL_ENTRY})
        result = get_quotes(client, "AAPL", extended=True)
        assert result["outcome"] == "ok"
        assert "provider" in result
        self._assert_clean(result, "ok extended quotes JSON")

    def test_quote_unavailable_has_no_secrets(self) -> None:
        from tests.unit.fixtures.quotes_payloads import UNKNOWN_SYMBOL_PAYLOAD

        from schwab_mcp.quotes import get_quotes

        self._register()
        client = self._client(quotes_payload=dict(UNKNOWN_SYMBOL_PAYLOAD))
        result = get_quotes(client, "ZOMB")
        assert result["outcome"] == "quote_unavailable"
        self._assert_clean(result, "quote_unavailable JSON")

    def test_validation_error_has_no_secrets(self) -> None:
        from schwab_mcp.quotes import get_quotes

        self._register()
        result = get_quotes(self._client(), ["BAD SYMBOL"])
        assert result["outcome"] == "validation_error"
        self._assert_clean(result, "validation_error JSON")

    def test_provider_unreachable_has_no_secrets(self) -> None:
        from schwab_mcp.quotes import get_quotes

        self._register()
        client = self._client(quotes_status=500)
        result = get_quotes(client, "AAPL")
        assert result["outcome"] == "provider_unreachable"
        self._assert_clean(result, "provider_unreachable JSON")

    def test_reauth_needed_has_no_secrets(self) -> None:
        from schwab_mcp.quotes import get_quotes

        self._register()
        client = self._client(quotes_status=401)
        result = get_quotes(client, "AAPL")
        assert result["outcome"] == "reauth_needed"
        self._assert_clean(result, "reauth_needed JSON")

    def test_audit_event_lines_have_no_secrets(self, capsys) -> None:
        """Real ``quotes_query_start``/``quotes_query_failure`` lines on
        stderr carry zero secrets (FR-010, redaction as defense-in-depth)."""
        from schwab_mcp.quotes import get_quotes

        self._register()
        client = self._client(market_hours_status=500)
        result = get_quotes(client, "AAPL")
        assert result["outcome"] == "provider_unreachable"

        stderr = capsys.readouterr().err
        assert "quotes_query_start" in stderr
        assert "quotes_query_failure" in stderr
        for secret in SECRET_MATERIAL:
            assert secret not in stderr, f"Secret {secret!r} leaked into events"
