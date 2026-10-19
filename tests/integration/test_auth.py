"""Failing integration tests for the authorization flow (User Story 1 / T013).

These tests verify the ``schwab-mcp auth`` subcommand end-to-end using a
stubbed/fake schwabdev Client (no network, no real credentials).

Because ``schwab_mcp.cli`` does **not exist yet**, every test will fail with
``ModuleNotFoundError`` at import time — this is the TDD red phase for T013.

After implementation (T014), these tests should pass and cover:

1. Empty store → auth triggers ``call_on_auth`` hook → URL printed & browser
   opened → paste prompt.
2. Successful paste → code exchange → success confirmation (zero secrets) →
   exit 0 → token store with ``0o600`` permissions → ``auth_start`` /
   ``auth_success`` events emitted per contracts/events.md.
3. Cancelled/empty paste → exit 3 with retry message → existing store
   untouched (FR-010).

References
----------
- FR-001: Explicit auth command, never implicit.
- FR-003: Token store ``0o600`` file / ``0o700`` directory.
- FR-006: Zero secrets in stdout / stderr output.
- FR-010: Existing store untouched until successful re-auth.
- FR-011: AuthLock prevents concurrent auth.
- FR-014: Auth events on stderr.
- contracts/cli.md : CLI exit codes and behavior.
- contracts/events.md : Auth event line format.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Callable, List

import pytest

# ---------------------------------------------------------------------------
# This import WILL raise ModuleNotFoundError because schwab_mcp.cli does not
# exist yet.  Every test in this file fails at import time during the TDD
# red phase.
# ---------------------------------------------------------------------------
from schwab_mcp.cli import main
from schwab_mcp.tokens import peek_store

# ---------------------------------------------------------------------------
# Fake schwabdev Client — mirrors the subset of schwabdev.v4.Client that the
# CLI interacts with.
# ---------------------------------------------------------------------------


class FakeSchwabdevClient:
    """A real-client-like stubbed schwabdev Client for testing the auth flow.

    Mirrors the subset of ``schwabdev.v4.Client`` that the CLI interacts
    with, INCLUDING the v4 auto-start behavior: when the token DB is empty,
    the constructor invokes ``call_on_auth(auth_url)`` and exchanges the
    pasted redirect URL for a token set.  The exchange is simulated: a
    paste containing ``code=`` writes a valid token store; anything else
    (empty paste, declined, error redirect) fails the exchange and the
    store stays empty — exactly like the real library, which only writes
    the row after a successful code exchange.
    """

    _instances: list["FakeSchwabdevClient"] = []

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        callback_url: str,
        tokens_db: str | os.PathLike,
        call_on_auth: Callable[[], str] | None = None,
        open_browser_for_auth: bool = False,
        **kwargs: Any,
    ) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.callback_url = callback_url
        self.tokens_db = str(tokens_db)
        self.call_on_auth = call_on_auth
        self.open_browser_for_auth = open_browser_for_auth
        self.hook_invocations = 0
        self.last_hook_url: str | None = None
        self.last_paste: str | None = None
        FakeSchwabdevClient._instances.append(self)
        # Real schwabdev v4 auto-starts the auth flow when the DB is empty.
        if call_on_auth is not None and not peek_store(self.tokens_db):
            self._run_auth_flow()

    def _auth_url(self) -> str:
        """Build the authorization URL the way schwabdev does."""
        return (
            "https://api.schwabapi.com/v1/oauth/authorize"
            f"?client_id={self.app_key}&redirect_uri={self.callback_url}"
        )

    def _run_auth_flow(self) -> None:
        """Invoke the hook once and simulate the code exchange."""
        assert self.call_on_auth is not None
        self.hook_invocations += 1
        self.last_hook_url = self._auth_url()
        redirect_url = self.call_on_auth(self.last_hook_url)
        self.last_paste = redirect_url
        if redirect_url and "code=" in redirect_url:
            # Simulated successful exchange: write the token set.
            _make_token_db(Path(self.tokens_db))

    def linked_accounts(self) -> dict[str, Any]:
        """Return a minimal fake response."""
        return {"accounts": [{"accountNumber": "12345678", "type": "MARGIN"}]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token_db(path: Path) -> Path:
    """Create a valid schwabdev SQLite token store at *path*.

    The schema matches what the real schwabdev library creates:
    a ``schwabdev`` table with access/refresh/id tokens.
    """
    import sqlite3

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
                "fake-access-token",
                "fake-refresh-token",
                "fake-id-token",
                "2026-10-19T12:00:00Z",
                "2026-10-19T12:00:00Z",
                1800,
                "Bearer",
                "readonly",
            ),
        )
        con.commit()
    finally:
        con.close()
    return path


def _capture_main(argv: list[str], **monkeypatch_kw: Any) -> dict[str, Any]:
    """Run ``main(argv)`` in a clean process context and capture outputs.

    Because ``main()`` calls ``sys.exit()`` on failure, running it inline
    would kill the test process.  Instead we run ``schwab-mcp auth`` as a
    subprocess with ``coverage`` disabled so we get clean stdout/stderr/rc.

    Returns
    -------
    dict with keys ``rc``, ``stdout``, ``stderr``, ``token_db_path``.
    """
    # This is a helper stub — the real implementation will be test-specific.
    # For now we document the expected API.
    raise NotImplementedError(
        "Inline main() is not safe because of sys.exit(); "
        "tests drive main directly and catch SystemExit."
    )


@pytest.fixture(autouse=True)
def _default_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Set up a clean environment with valid but fake credentials."""
    monkeypatch.setenv("SCHWAB_APP_KEY", "TEST_APP_KEY_32CHARS__FILLER")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "TEST_APP_SECRET_32CHAR_FILLER")
    monkeypatch.setenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1")
    token_db = str(tmp_path / "tokens.db")
    monkeypatch.setenv("SCHWAB_TOKEN_DB", token_db)
    # Ensure the tmp directory exists
    tmp_path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Paste simulation (T026) — the owner "pastes" the redirect URL at the
# terminal prompt, which the CLI reads via ``input()``.
# ---------------------------------------------------------------------------

FAKE_CODE = "FAKE_AUTH_CODE_123456"
PASTED_REDIRECT_URL = f"https://127.0.0.1/?code={FAKE_CODE}&session=state123"
PASTED_ERROR_URL = "https://127.0.0.1/?error=access_denied"


def _paste(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Make ``input()`` (the paste prompt) return *value*."""
    monkeypatch.setattr("builtins.input", lambda *a: value)


def _no_browser(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stub ``webbrowser.open`` (never open a real browser); returns the
    list of opened URLs."""
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    return opened


# ===================================================================
# 1. Empty store → auth triggers authorization flow
# ===================================================================


class TestEmptyStoreTriggersAuthFlow:
    """When the token store is empty/absent, ``auth`` triggers the
    ``call_on_auth`` hook and prints the authorization URL."""

    def test_missing_store_triggers_call_on_auth(self, monkeypatch, tmp_path):
        """No token store → ``call_on_auth`` is invoked by the CLI.

        The hook must print an authorization URL to stdout and attempt
        to open the system browser.
        """
        # We capture the hook invocation by patching the module's client.
        # The CLI should call schwabdev.Client(..., call_on_auth=<hook>).
        # Here we verify that a missing store causes main() to reach
        # the auth flow rather than failing early.
        invoked = []
        auth_url = "https://api.schwabapi.com/v1/oauth/authorize?client_id=TEST_APP_KEY"

        # Patch schwabdev so the CLI uses our fake
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        _paste(monkeypatch, PASTED_REDIRECT_URL)
        _no_browser(monkeypatch)
        FakeSchwabdevClient._instances.clear()

        with pytest.raises(SystemExit) as exc_info:
            main(["auth"])

        # --- Assertions ---
        assert exc_info.value.code == 0, (
            f"Expected exit 0 on successful auth, got {exc_info.value.code}"
        )

        # The client was constructed with the hook and the flow completed
        # with exactly one hook invocation (single prompt, T026).
        assert len(FakeSchwabdevClient._instances) == 1, (
            "Expected exactly one FakeSchwabdevClient to be constructed"
        )
        assert FakeSchwabdevClient._instances[0].hook_invocations == 1, (
            "Expected the call_on_auth hook to have been invoked exactly once"
        )

    def test_hook_prints_auth_url_and_opens_browser(
        self, monkeypatch, tmp_path
    ):
        """The ``call_on_auth`` hook prints the authorization URL to stdout
        and opens the system browser at that URL."""
        printed_lines: list[str] = []
        opened_urls = _no_browser(monkeypatch)
        _paste(monkeypatch, PASTED_REDIRECT_URL)

        def fake_print(*args, **kwargs):
            printed_lines.extend(str(a) for a in args)

        monkeypatch.setattr("builtins.print", fake_print)
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )

        # The auth URL should contain the client ID and redirect URI
        with pytest.raises(SystemExit):
            main(["auth"])

        url_lines = [l for l in printed_lines if "schwabapi.com" in l]
        assert url_lines, (
            "Expected at least one printed line containing the "
            "Schwab authorization URL"
        )
        assert opened_urls, (
            "Expected webbrowser.open to have been called with the "
            "authorization URL"
        )

        auth_url = url_lines[0]
        assert "client_id=" in auth_url, (
            "Authorization URL must include the client_id parameter"
        )
        assert "redirect_uri=" in auth_url, (
            "Authorization URL must include the redirect_uri parameter"
        )

    def test_browser_open_failure_falls_back_to_url_only_prompt(
        self, monkeypatch, tmp_path
    ):
        """When ``webbrowser.open`` returns False (cannot open browser),
        the flow must NOT hang — it should fall back to showing the URL
        and continuing with the paste prompt."""
        printed_lines: list[str] = []
        _paste(monkeypatch, PASTED_REDIRECT_URL)

        def fake_print(*args, **kwargs):
            printed_lines.extend(str(a) for a in args)

        monkeypatch.setattr("builtins.print", fake_print)
        # Browser fails to open
        monkeypatch.setattr("webbrowser.open", lambda url: False)
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit):
            main(["auth"])

        # The URL must still be printed
        url_lines = [l for l in printed_lines if "schwabapi.com" in l]
        assert url_lines, (
            "Even when the browser fails to open, the authorization "
            "URL must be printed so the owner can visit it manually"
        )

    def test_hook_returns_pasted_redirect_url(self, monkeypatch, tmp_path):
        """The hook must prompt the owner to paste the redirect URL and
        return the pasted value to schwabdev for code exchange."""
        # The CLI should call schwabdev's Client with a call_on_auth hook
        # that accepts user input (the pasted redirect URL).  The hook
        # must return the pasted value.
        captured_client: FakeSchwabdevClient | None = None
        orig_fake = FakeSchwabdevClient

        def capturing_client(*args, **kwargs):
            nonlocal captured_client
            captured_client = orig_fake(*args, **kwargs)
            return captured_client

        monkeypatch.setattr("schwab_mcp.cli.schwabdev.Client", capturing_client)
        # Simulate a pasted redirect URL via stdin or hook return value

        with pytest.raises(SystemExit):
            main(["auth"])

        assert captured_client is not None, (
            "A schwabdev Client should have been instantiated"
        )
        assert captured_client.call_on_auth is not None, (
            "The client must be constructed with a call_on_auth hook"
        )


# ===================================================================
# 2. Successful paste → token exchange → exit 0
# ===================================================================


class TestSuccessfulAuth:
    """Complete auth flow: empty store → paste → exchange → success."""

    def test_exit_code_zero_on_success(self, monkeypatch, tmp_path):
        """A completed auth flow exits with code 0."""
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        _paste(monkeypatch, PASTED_REDIRECT_URL)
        _no_browser(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            main(["auth"])

        assert exc_info.value.code == 0, (
            f"Expected exit code 0 for successful auth, "
            f"got {exc_info.value.code}"
        )

    def test_token_store_exists_after_success(self, monkeypatch, tmp_path):
        """After successful auth, the token DB file exists at the configured
        path."""
        token_db = tmp_path / "tokens.db"
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(token_db))
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        _paste(monkeypatch, PASTED_REDIRECT_URL)
        _no_browser(monkeypatch)

        with pytest.raises(SystemExit):
            main(["auth"])

        assert token_db.exists(), (
            f"Token store should exist at {token_db} after successful auth"
        )

    def test_token_store_permissions_0600(self, monkeypatch, tmp_path):
        """The token DB file must be readable/writable only by the owner
        (0o600) per FR-003."""
        token_db = tmp_path / "tokens.db"
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(token_db))
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        _paste(monkeypatch, PASTED_REDIRECT_URL)
        _no_browser(monkeypatch)

        with pytest.raises(SystemExit):
            main(["auth"])

        if token_db.exists():
            mode = stat.S_IMODE(os.stat(token_db).st_mode)
            assert mode == 0o600, (
                f"Expected token DB permissions 0o600, got {oct(mode)} "
                f"(FR-003)"
            )

    def test_success_confirmation_printed_without_secrets(
        self, monkeypatch, tmp_path
    ):
        """The success confirmation must be printed to stdout/stderr but
        contain NO secret material (NO app key, app secret, access token,
        refresh token)."""
        captured_stdout: list[str] = []
        captured_stderr: list[str] = []

        def tracking_print(*args, **kwargs):
            file = kwargs.get("file", sys.stdout)
            text = " ".join(str(a) for a in args)
            if file is sys.stderr:
                captured_stderr.append(text)
            else:
                captured_stdout.append(text)

        monkeypatch.setattr("builtins.print", tracking_print)
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )

        app_key = "TEST_APP_KEY_32CHARS__FILLER"
        app_secret = "TEST_APP_SECRET_32CHAR_FILLER"
        _paste(monkeypatch, PASTED_REDIRECT_URL)
        _no_browser(monkeypatch)

        with pytest.raises(SystemExit):
            main(["auth"])

        all_output = "\n".join(captured_stdout + captured_stderr)

        # FR-006 (amended): zero occurrences of secret material. The app
        # key (client_id) is public by OAuth design and may appear ONLY
        # inside the displayed authorization URL, which must be usable
        # as-is; everywhere else it must not appear.
        auth_url_lines = [
            line for line in all_output.splitlines()
            if "api.schwabapi.com/v1/oauth/authorize" in line
        ]
        outside_url = "\n".join(
            line for line in all_output.splitlines()
            if "api.schwabapi.com/v1/oauth/authorize" not in line
        )
        assert app_key not in outside_url, (
            f"App key leaked outside the authorization URL: {all_output!r}"
        )
        if auth_url_lines:
            assert f"client_id={app_key}" in auth_url_lines[0], (
                "Displayed authorization URL must contain the client_id "
                "in full (amended FR-006)"
            )
        assert app_secret not in all_output, (
            f"App secret leaked into output: {all_output!r}"
        )
        assert "fake-access-token" not in all_output, (
            "Access token leaked into output (FR-006)"
        )
        assert "fake-refresh-token" not in all_output, (
            "Refresh token leaked into output (FR-006)"
        )

    def test_auth_start_event_emitted(self, monkeypatch, tmp_path):
        """An ``auth_start`` event with ``outcome=initiated`` is emitted to
        stderr after config validation and lock acquisition."""
        captured_stderr: list[str] = []

        def tracking_print(*args, **kwargs):
            file = kwargs.get("file", sys.stdout)
            text = " ".join(str(a) for a in args)
            if file is sys.stderr:
                captured_stderr.append(text)

        monkeypatch.setattr("builtins.print", tracking_print)
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        _paste(monkeypatch, PASTED_REDIRECT_URL)
        _no_browser(monkeypatch)

        with pytest.raises(SystemExit):
            main(["auth"])

        stderr_text = "\n".join(captured_stderr)
        assert "auth_event=auth_start" in stderr_text, (
            "Expected 'auth_event=auth_start' in stderr output, "
            f"got:\n{stderr_text}"
        )
        assert "outcome=initiated" in stderr_text, (
            "Expected 'outcome=initiated' alongside auth_start event"
        )

    def test_auth_success_event_emitted(self, monkeypatch, tmp_path):
        """An ``auth_success`` event with ``outcome=ok`` is emitted to
        stderr after the token set is stored."""
        captured_stderr: list[str] = []

        def tracking_print(*args, **kwargs):
            file = kwargs.get("file", sys.stdout)
            text = " ".join(str(a) for a in args)
            if file is sys.stderr:
                captured_stderr.append(text)

        monkeypatch.setattr("builtins.print", tracking_print)
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        _paste(monkeypatch, PASTED_REDIRECT_URL)
        _no_browser(monkeypatch)

        with pytest.raises(SystemExit):
            main(["auth"])

        stderr_text = "\n".join(captured_stderr)
        assert "auth_event=auth_success" in stderr_text, (
            "Expected 'auth_event=auth_success' in stderr output, "
            f"got:\n{stderr_text}"
        )
        assert "outcome=ok" in stderr_text, (
            "Expected 'outcome=ok' alongside auth_success event"
        )

    def test_output_contains_code_or_exchange_reference(
        self, monkeypatch, tmp_path
    ):
        """The success output should indicate that the token exchange
        completed — a message like "Authorization successful".
        FR-006: no secrets in that message."""
        captured_stdout: list[str] = []

        def tracking_print(*args, **kwargs):
            file = kwargs.get("file", sys.stdout)
            text = " ".join(str(a) for a in args)
            if file is sys.stdout:
                captured_stdout.append(text)

        monkeypatch.setattr("builtins.print", tracking_print)
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        _paste(monkeypatch, PASTED_REDIRECT_URL)
        _no_browser(monkeypatch)

        with pytest.raises(SystemExit):
            main(["auth"])

        output = "\n".join(captured_stdout).lower()
        keywords = ["success", "authorized", "completed", "exchange", "done"]
        assert any(kw in output for kw in keywords), (
            f"Expected a success message ('success', 'authorized', etc.) "
            f"in output, got:\n{captured_stdout}"
        )


# ===================================================================
# 3. Cancelled / empty paste → exit 3
# ===================================================================


class TestCancelledAuth:
    """When the owner provides an empty/cancelled paste, the auth flow
    must abort with exit code 3 and leave the existing store untouched
    (FR-010)."""

    def test_empty_paste_exits_code_3(self, monkeypatch, tmp_path):
        """An empty paste (empty string) should cause exit code 3 with
        the ``AuthorizationCancelledError`` message."""
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        # Simulate interactive stdin (required for cancellation detection).
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        with pytest.raises(SystemExit) as exc_info:
            main(["auth"])

        # Exit 3 = AuthorizationCancelledError
        assert exc_info.value.code == 3, (
            f"Expected exit code 3 for cancelled auth, "
            f"got {exc_info.value.code}"
        )

    def test_cancelled_retry_message_printed(self, monkeypatch, tmp_path):
        """After a cancelled paste, the output should include the retry
        message ('Re-run schwab-mcp auth to retry')."""
        captured_stdout: list[str] = []
        captured_stderr: list[str] = []

        def tracking_print(*args, **kwargs):
            file = kwargs.get("file", sys.stdout)
            text = " ".join(str(a) for a in args)
            if file is sys.stderr:
                captured_stderr.append(text)
            else:
                captured_stdout.append(text)

        monkeypatch.setattr("builtins.print", tracking_print)
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        # Simulate interactive stdin (required for cancellation detection).
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        with pytest.raises(SystemExit):
            main(["auth"])

        all_output = "\n".join(captured_stdout + captured_stderr)
        assert "Re-run" in all_output or "schwab-mcp auth" in all_output, (
            "Expected a retry message ('Re-run schwab-mcp auth to retry') "
            f"in output, got:\n{all_output}"
        )

    def test_existing_store_untouched_on_cancelled(
        self, monkeypatch, tmp_path
    ):
        """FR-010: When the auth flow is cancelled, an existing valid token
        store must NOT be modified."""
        # Pre-create a valid token store
        token_db = tmp_path / "tokens.db"
        _make_token_db(token_db)
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(token_db))

        # Record the original content
        original_content = token_db.read_bytes()

        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit):
            main(["auth"])

        # The store must be unchanged
        assert token_db.exists(), "Token store must still exist after cancelled auth"
        assert token_db.read_bytes() == original_content, (
            "FR-010: An existing valid token store must not be modified "
            "when the auth flow is cancelled"
        )

    def test_auth_failure_event_on_cancelled(self, monkeypatch, tmp_path):
        """An ``auth_failure`` event with ``outcome=cancelled`` is emitted
        when the paste is cancelled/empty."""
        captured_stderr: list[str] = []

        def tracking_print(*args, **kwargs):
            file = kwargs.get("file", sys.stdout)
            text = " ".join(str(a) for a in args)
            if file is sys.stderr:
                captured_stderr.append(text)

        monkeypatch.setattr("builtins.print", tracking_print)
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        # Simulate interactive stdin (required for cancellation detection).
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        with pytest.raises(SystemExit):
            main(["auth"])

        stderr_text = "\n".join(captured_stderr)
        assert "auth_event=auth_failure" in stderr_text, (
            "Expected 'auth_event=auth_failure' in stderr output "
            f"for cancelled auth, got:\n{stderr_text}"
        )
        assert "outcome=cancelled" in stderr_text, (
            "Expected 'outcome=cancelled' for auth_failure event"
        )


# ===================================================================
# 3b. Completion detection is store-based, never paste/TTY-based (T026)
#     FR-007, FR-002, US1/AC1, contracts/cli.md Behavior 3–5.
# ===================================================================


class TestAuthCompletionDetection:
    """``auth`` must report success ONLY when a usable token set is
    actually stored (``peek_store``), never merely because a string was
    pasted or because stdin is/is not a TTY.  A flow that ends without a
    stored token set (empty paste — interactive or not — or a paste whose
    exchange failed) must exit 3 with the ``auth_failure`` event and must
    never print a success confirmation (FR-007, FR-002, US1/AC1)."""

    def test_non_interactive_empty_paste_exits_3(
        self, monkeypatch, tmp_path
    ):
        """FR-007: An empty paste with NON-interactive stdin (isatty False —
        e.g. piped/EOF input) must exit 3 with the cancellation message and
        ``auth_failure`` event — never a false success."""
        captured_stdout: list[str] = []
        captured_stderr: list[str] = []

        def tracking_print(*args, **kwargs):
            file = kwargs.get("file", sys.stdout)
            text = " ".join(str(a) for a in args)
            if file is sys.stderr:
                captured_stderr.append(text)
            else:
                captured_stdout.append(text)

        monkeypatch.setattr("builtins.print", tracking_print)
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        _paste(monkeypatch, "")  # EOF-like empty paste
        _no_browser(monkeypatch)
        # NOTE: sys.stdin.isatty intentionally NOT patched (False under pytest)

        with pytest.raises(SystemExit) as exc_info:
            main(["auth"])

        assert exc_info.value.code == 3, (
            f"Expected exit code 3 for non-interactive empty paste, "
            f"got {exc_info.value.code}"
        )
        stderr_text = "\n".join(captured_stderr)
        assert "auth_event=auth_failure" in stderr_text, (
            f"Expected auth_failure event, got:\n{stderr_text}"
        )
        assert "outcome=cancelled" in stderr_text
        assert "Re-run" in stderr_text or "schwab-mcp auth" in stderr_text
        all_output = "\n".join(captured_stdout + captured_stderr)
        assert "Authorization successful" not in all_output, (
            "A cancelled flow must NEVER print a success confirmation"
        )
        assert "auth_event=auth_success" not in stderr_text, (
            "A cancelled flow must NEVER emit auth_success"
        )

    def test_failed_exchange_never_reports_success(
        self, monkeypatch, tmp_path
    ):
        """FR-002/FR-007: A paste whose exchange fails (no ``code=``, store
        stays empty) must exit 3 — never success/exit 0."""
        captured_stdout: list[str] = []
        captured_stderr: list[str] = []

        def tracking_print(*args, **kwargs):
            file = kwargs.get("file", sys.stdout)
            text = " ".join(str(a) for a in args)
            if file is sys.stderr:
                captured_stderr.append(text)
            else:
                captured_stdout.append(text)

        monkeypatch.setattr("builtins.print", tracking_print)
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        _paste(monkeypatch, PASTED_ERROR_URL)  # non-empty but exchange fails
        _no_browser(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            main(["auth"])

        assert exc_info.value.code == 3, (
            f"Expected exit code 3 for failed exchange, got {exc_info.value.code}"
        )
        stderr_text = "\n".join(captured_stderr)
        assert "auth_event=auth_failure" in stderr_text, (
            f"Expected auth_failure event for failed exchange, got:\n{stderr_text}"
        )
        all_output = "\n".join(captured_stdout + captured_stderr)
        assert "Authorization successful" not in all_output, (
            "A flow without a stored token set must NEVER print success"
        )
        assert "auth_event=auth_success" not in stderr_text
        assert not peek_store(str(tmp_path / "tokens.db")), (
            "No token set may be stored after a failed exchange"
        )

    def test_success_requires_stored_token_set(
        self, monkeypatch, tmp_path
    ):
        """US1/AC1: Exit 0 + ``auth_success`` ONLY when the token set is
        stored; with a successful paste the store exists and the flow
        succeeds."""
        captured_stderr: list[str] = []

        def tracking_print(*args, **kwargs):
            file = kwargs.get("file", sys.stdout)
            text = " ".join(str(a) for a in args)
            if file is sys.stderr:
                captured_stderr.append(text)

        monkeypatch.setattr("builtins.print", tracking_print)
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        _paste(monkeypatch, PASTED_REDIRECT_URL)
        _no_browser(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            main(["auth"])

        assert exc_info.value.code == 0
        assert peek_store(str(tmp_path / "tokens.db")), (
            "US1/AC1: a successful auth must have stored a usable token set"
        )
        assert "auth_event=auth_success" in "\n".join(captured_stderr)

    def test_single_prompt_with_auto_invoking_client(
        self, monkeypatch, tmp_path
    ):
        """contracts/cli.md Behavior 3: with a real-client-like stub that
        auto-invokes the hook, the URL print / browser open / paste prompt
        happen exactly ONCE per attempt — even when the attempt ends in
        cancellation (no double prompt)."""
        opened = _no_browser(monkeypatch)
        _paste(monkeypatch, "")  # owner declines at the prompt
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        FakeSchwabdevClient._instances.clear()

        with pytest.raises(SystemExit) as exc_info:
            main(["auth"])

        assert exc_info.value.code == 3
        assert len(FakeSchwabdevClient._instances) == 1
        client = FakeSchwabdevClient._instances[0]
        assert client.hook_invocations == 1, (
            f"The hook must be invoked exactly once per attempt, "
            f"got {client.hook_invocations} (double prompt violates "
            "contracts/cli.md Behavior 3)"
        )
        assert len(opened) == 1, (
            f"Browser must open exactly once, got {len(opened)} attempts"
        )


# ===================================================================
# 4. Concurrent auth → exit 6 (FR-011)
# ===================================================================


class TestConcurrentAuth:
    """Concurrent ``schwab-mcp auth`` attempts are refused with exit 6."""

    def test_concurrent_auth_refused_exit_6(self, monkeypatch, tmp_path):
        """When another auth process holds the advisory lock, a second
        ``auth`` invocation must refuse with exit code 6."""
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )

        # Actually hold the fcntl lock on the advisory lock file so the second
        # AuthLock attempt fails with ConcurrentAuthError.
        # T028: the advisory lock lives at <token-db-dir>/auth.lock.
        import fcntl
        import os
        lock_path = str(tmp_path / "auth.lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)

        try:
            with pytest.raises(SystemExit) as exc_info:
                main(["auth"])

            assert exc_info.value.code == 6, (
                f"Expected exit code 6 for concurrent auth, "
                f"got {exc_info.value.code}"
            )
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_concurrent_retry_message(self, monkeypatch, tmp_path):
        """The concurrent-auth refusal message must mention the retry
        action ('Another authorization is already running')."""
        captured_stderr: list[str] = []

        def tracking_print(*args, **kwargs):
            file = kwargs.get("file", sys.stdout)
            text = " ".join(str(a) for a in args)
            if file is sys.stderr:
                captured_stderr.append(text)

        monkeypatch.setattr("builtins.print", tracking_print)
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )

        # Hold the fcntl lock to simulate concurrent auth.
        # T028: the advisory lock lives at <token-db-dir>/auth.lock.
        import fcntl
        import os
        lock_path = str(tmp_path / "auth.lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)

        try:
            with pytest.raises(SystemExit):
                main(["auth"])

            all_output = "\n".join(captured_stderr)
            assert "already" in all_output.lower() or "wait" in all_output.lower(), (
                "Expected a concurrent-auth refusal message ('Another "
                f"authorization is already running'), got:\n{all_output}"
            )
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


# ===================================================================
# 5. Missing / invalid config → fast fail before any auth flow
# ===================================================================


class TestMissingConfigBeforeAuth:
    """Missing or invalid config must fail BEFORE any auth flow starts
    (FR-008)."""

    def test_missing_app_key_does_not_invoke_call_on_auth(
        self, monkeypatch, tmp_path
    ):
        """When SCHWAB_APP_KEY is missing, the auth command must fail
        without attempting to construct a schwabdev Client or invoke
        any auth hooks."""
        monkeypatch.delenv("SCHWAB_APP_KEY", raising=False)
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["auth"])

        assert exc_info.value.code == 2, (
            f"Expected exit code 2 for missing config, "
            f"got {exc_info.value.code}"
        )

    def test_missing_app_secret_does_not_open_browser(
        self, monkeypatch, tmp_path
    ):
        """When SCHWAB_APP_SECRET is missing, no browser should open."""
        monkeypatch.delenv("SCHWAB_APP_SECRET", raising=False)
        opened: list[str] = []
        monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

        with pytest.raises(SystemExit):
            main(["auth"])

        assert not opened, (
            "Browser must NOT open when config is missing (fail fast, FR-008)"
        )


# ===================================================================
# 6. Edge cases
# ===================================================================


class TestEdgeCases:
    """Corner-case scenarios."""

    def test_auth_subcommand_help(self, monkeypatch, tmp_path):
        """``schwab-mcp auth --help`` prints usage and exits 0 without
        any config or network activity."""
        with pytest.raises(SystemExit) as exc_info:
            main(["auth", "--help"])

        assert exc_info.value.code == 0, (
            "Expected exit 0 for --help"
        )

    def test_unknown_command_shows_error(self, monkeypatch, tmp_path):
        """An unknown subcommand should produce an error and nonzero exit."""
        with pytest.raises(SystemExit) as exc_info:
            main(["unknown-command"])

        assert exc_info.value.code != 0, (
            "Expected nonzero exit for unknown subcommand"
        )

    def test_auth_failure_event_on_paste_error(self, monkeypatch, tmp_path):
        """If a non-cancellation error occurs during the auth flow (e.g.
        invalid code exchange), an ``auth_failure`` event with
        ``outcome=failed`` is emitted."""
        captured_stderr: list[str] = []

        def tracking_print(*args, **kwargs):
            file = kwargs.get("file", sys.stdout)
            text = " ".join(str(a) for a in args)
            if file is sys.stderr:
                captured_stderr.append(text)

        monkeypatch.setattr("builtins.print", tracking_print)
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )
        # Simulate interactive stdin (required for cancellation detection).
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        with pytest.raises(SystemExit):
            main(["auth"])

        stderr_text = "\n".join(captured_stderr)
        # The auth_failure event should specify what went wrong
        assert "auth_event=auth_failure" in stderr_text, (
            "Expected an auth_failure event on failed paste, "
            f"got:\n{stderr_text}"
        )


# ===================================================================
# 7. Round-trip: run auth twice without issues
# ===================================================================


class TestReauthFlow:
    """Running ``schwab-mcp auth`` again after a previous successful auth
    (re-auth) should succeed without corrupting the existing store until
    the new auth completes (FR-010)."""

    def test_reauth_on_existing_store_succeeds(self, monkeypatch, tmp_path):
        """Running ``auth`` again with an existing valid store succeeds."""
        token_db = tmp_path / "tokens.db"
        _make_token_db(token_db)
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(token_db))
        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["auth"])

        assert exc_info.value.code == 0, (
            f"Expected exit 0 on re-auth, got {exc_info.value.code}"
        )

    def test_existing_store_survives_until_new_auth_completes(
        self, monkeypatch, tmp_path
    ):
        """FR-010: The existing valid token set must survive when the
        re-auth flow aborts."""
        token_db = tmp_path / "tokens.db"
        _make_token_db(token_db)
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(token_db))
        original_content = token_db.read_bytes()

        monkeypatch.setattr(
            "schwab_mcp.cli.schwabdev.Client", FakeSchwabdevClient
        )

        # Simulate a failed re-auth
        with pytest.raises(SystemExit):
            main(["auth"])

        assert token_db.read_bytes() == original_content, (
            "FR-010: Existing valid store must survive failed re-auth"
        )