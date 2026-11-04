"""schwab-mcp CLI entry point (console_scripts)."""

from __future__ import annotations

import argparse
import logging
import sys
import webbrowser
from collections.abc import Callable
from functools import partial
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path

import schwabdev  # Module-level import so monkeypatch can patch schwabdev.Client

from schwab_mcp.config import load_config
from schwab_mcp.errors import (
    AuthError,
    AuthorizationCancelledError,
    ConcurrentAuthError,
    TokenStoreCorruptedError,
)
from schwab_mcp.log import auth_event, install_redaction_filter
from schwab_mcp.renewal import AuthHealth, RenewalOutcome, read_store_lifetime, renew as _renew
from schwab_mcp.tokens import (
    AuthLock,
    backup_token_store,
    discard_token_store_backup,
    enforce_permissions,
    peek_store_status,
    quarantine_corrupt_store,
    restore_token_store,
)


def _build_auth_url(app_key: str, callback_url: str) -> str:
    """Build the Schwab OAuth authorization URL."""
    import urllib.parse

    return (
        "https://api.schwabapi.com/v1/oauth/authorize"
        f"?client_id={urllib.parse.quote(app_key)}"
        f"&redirect_uri={urllib.parse.quote(callback_url)}"
    )


def _read_store_bytes(path: str) -> bytes | None:
    """Raw store bytes, or ``None`` when the store does not exist.

    Used as fresh-write evidence by the success gate in :func:`run_auth`.
    """
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def _prompt_for_paste() -> str:
    """Prompt the owner to paste the redirect URL and return it stripped.

    Returns an empty string if no input is available (non-interactive).
    """
    try:
        return input("Paste the redirect URL: ").strip()
    except (EOFError, OSError):
        return ""


def auth_hook(auth_url: str) -> str:
    """Call-on-auth hook passed to schwabdev's Client constructor.

    Prints the full authorization URL to stdout and opens the system
    browser at the same URL.  The client_id (app key) is public by OAuth
    design and MUST appear in full so the printed URL is usable as-is
    (amended FR-006); the app secret, tokens, and authorization codes
    remain redacted everywhere by the logging filter.  Returns the pasted
    redirect URL, or an empty string if no input was available.
    """
    print(auth_url)
    opened = webbrowser.open(auth_url)
    if not opened:
        print(
            "Unable to open browser automatically. "
            "Please visit the URL above and paste the redirect URL."
        )
    return _prompt_for_paste()


def run_auth() -> None:
    """Execute the ``auth`` subcommand."""
    config = load_config()

    lock_path = config.token_db
    with AuthLock(lock_path):
        # Bug auth-corrupt-store-blocked: a corrupted store must not block
        # re-authorization.  The old guard raised TokenStoreCorruptedError
        # (exit 5) with a message telling the user to re-run ``auth`` — the
        # same command that kept failing.  Quarantine the unusable file
        # (FR-009: treated as absent, preserved for forensics) and let the
        # fresh flow below proceed.  Quarantine happens inside the lock so
        # concurrent runs cannot race on the rename.
        quarantined: Path | None = None
        if peek_store_status(config.token_db) == "corrupted":
            try:
                quarantined = quarantine_corrupt_store(config.token_db)
            except OSError:
                # Unmovable store (permissions): keep the old clean exit
                # instead of a raw traceback.
                raise TokenStoreCorruptedError(
                    detail="Store could not be quarantined; fix permissions and re-run"
                ) from None
        auth_event(
            "auth_start", "initiated",
            f"corrupt store quarantined: {quarantined.name}"
            if quarantined
            else "browser flow requested",
        )

        # Bug auth-false-success: ``auth`` is a deliberate re-authorization
        # and must never trust the rows already in the store — a refresh
        # token revoked server-side looks identical to a fresh one to any
        # store read, and schwabdev's init-time silent refresh then
        # fails (invalid_grant) without ever reaching the hook.  Move the
        # store aside so the client performs a REAL authorization-code
        # flow through ``call_on_auth``; restore the previous store
        # untouched if this run does not complete (FR-010).
        pre_bytes = _read_store_bytes(config.token_db)
        backup_path = backup_token_store(config.token_db)
        try:
            # The hook runs exactly once per attempt.  schwabdev's Client
            # constructor invokes call_on_auth itself whenever the token store
            # is empty (v4 auto-start); a client that did NOT invoke it (inert
            # stubs) gets one manual invocation below.  Counting invocations
            # is what prevents the double URL-print/prompt.
            hook_calls = 0
            last_paste = ""

            def counted_hook(auth_url: str) -> str:
                nonlocal hook_calls, last_paste
                hook_calls += 1
                last_paste = auth_hook(auth_url)
                return last_paste

            # schwabdev's Client constructor invokes call_on_auth when the
            # token store is empty, performing the code exchange and writing
            # tokens before returning.  The trailing-slash callback shim is
            # installed by build_schwab_client itself (TD-012).
            from schwab_mcp.client import build_schwab_client  # noqa: PLC0415 — late import for testability

            build_schwab_client(config, config.token_db, counted_hook)

            # Fallback (td-018): production schwabdev always invokes the
            # hook itself when the store is empty (v4 auto-start), so this
            # branch is unreachable with the real client.  It is kept as
            # deliberate hardening: if the hook timing ever changes (today
            # it is exercised by inert test stubs), ``auth`` must still
            # print the URL and prompt rather than fail silently.
            # (TD-003: the status-based check replaces the deleted
            # peek_store; a corrupted store is unreachable here —
            # quarantined above, and the store is moved aside by
            # backup_token_store before this point.)
            if peek_store_status(config.token_db) == "absent" and hook_calls == 0:
                auth_url = _build_auth_url(config.app_key, config.callback_url)
                counted_hook(auth_url)

            # Success requires a usable store AND evidence of a fresh write
            # during THIS run: the hook ran, or the store content differs
            # from the pre-run bytes.  Unchanged rows that merely survived
            # the run are never a success (auth-false-success).
            fresh_write = (
                hook_calls > 0
                or _read_store_bytes(config.token_db) != pre_bytes
            )
            if peek_store_status(config.token_db) == "absent" or not fresh_write:
                if last_paste:
                    auth_event(
                        "auth_failure", "failed",
                        "check the pasted redirect URL; run: schwab-mcp auth to retry",
                    )
                else:
                    auth_event(
                        "auth_failure", "cancelled",
                        "run: schwab-mcp auth to retry",
                    )
                raise AuthorizationCancelledError()
        except BaseException:
            # Any failure/cancel path restores the previous store
            # byte-identically (FR-010) — a cancelled auth must not destroy
            # possibly-valid credentials.
            restore_token_store(backup_path, config.token_db)
            raise

        # Fresh token set stored: the pre-flow backup is now obsolete.
        discard_token_store_backup(backup_path)

        # Enforce restrictive permissions on the freshly stored token set.
        enforce_permissions(config.token_db)

        print("Authorization successful. Schwab API access is configured.")
        # Bug renew-phantom-success (Issue 2): Schwab allows only ONE active
        # token set per app key + user.  Completing this authorization
        # revokes every token set previously issued to other installations
        # sharing the same app key — make that visible instead of leaving
        # the operator to discover it later as a mysterious invalid_grant.
        print(
            "Note: any other installation using this app key (another "
            "machine, server, or integration) has now had its token set "
            "revoked by Schwab.",
            file=sys.stderr,
        )
        auth_event(
            "auth_success", "ok",
            "token set stored; other installations sharing this app key "
            "are now revoked",
        )


def run_auth_status() -> None:
    """Execute the ``auth-status`` subcommand (FR-008).

    Strictly read-only: never constructs a ``schwabdev.Client``,
    never touches the network, never triggers a renewal.  Answers in
    one shot (SC-003), ≤ 2 s.
    """
    config = load_config()
    store_path = config.token_db

    status = peek_store_status(store_path)
    if status == "absent":
        health = AuthHealth(
            state="reauth_required",
            access_expires_in_seconds=None,
            refresh_expires_in_seconds=None,
        )
        print(health.to_json())
        sys.exit(3)

    if status == "corrupted":
        health = AuthHealth(
            state="reauth_required",
            access_expires_in_seconds=None,
            refresh_expires_in_seconds=None,
        )
        print(health.to_json())
        sys.exit(3)

    lifetime = read_store_lifetime(store_path)
    if lifetime is None:
        health = AuthHealth(
            state="reauth_required",
            access_expires_in_seconds=None,
            refresh_expires_in_seconds=None,
        )
    else:
        health = AuthHealth(
            state="valid",
            access_expires_in_seconds=lifetime.access_remaining_seconds,
            refresh_expires_in_seconds=lifetime.refresh_remaining_seconds,
        )
    print(health.to_json())
    sys.exit(0)


def run_renew() -> None:
    """Execute the ``renew`` subcommand (FR-002).

    Sequence
    --------
    1. Load configuration (fail-fast).
    2. Peek the token store: absent / corrupted → exit 3.
    3. Read remaining validity; above margin → exit 0 (not_needed).
    4. Acquire ``AuthLock`` (non-blocking); busy → exit 6.
    5. Build the schwabdev client and call ``renew()``.
    6. Print exactly one JSON line on stdout.
    7. Map outcome to exit code per contracts/cli.md.
    """
    config = load_config()
    store_path = config.token_db

    # 2. Store peek: absent / corrupted → reauth_required, exit 3
    status = peek_store_status(store_path)
    if status == "absent":
        outcome = RenewalOutcome(
            outcome="reauth_required",
            expires_in_seconds=None,
            retryable=False,
            detail="store_absent",
        )
        print(outcome.to_json())
        auth_event("renewal_failure", "reauth_required",
                    detail="run: schwab-mcp auth")
        sys.exit(3)

    if status == "corrupted":
        outcome = RenewalOutcome(
            outcome="reauth_required",
            expires_in_seconds=None,
            retryable=False,
            detail="store_corrupted",
        )
        print(outcome.to_json())
        auth_event("renewal_failure", "reauth_required",
                    detail="run: schwab-mcp auth")
        sys.exit(3)

    # 4. Acquire AuthLock (non-blocking); busy → exit 6
    try:
        with AuthLock(store_path):
            _do_run_renew(config, store_path)
    except ConcurrentAuthError:
        auth_event("renewal_failure", "reauth_required",
                    detail="another renewal already in progress")
        sys.exit(6)


def _do_run_renew(config: object, store_path: str) -> None:
    """Build the client and execute ``renew()`` (under ``AuthLock``)."""
    from schwab_mcp.client import build_schwab_client  # noqa: PLC0415 — late import for testability

    from schwab_mcp.server import _build_serve_guard_hook

    guard_hook = _build_serve_guard_hook()

    # Use the same guard hook as ``serve`` — in the explicit CLI command,
    # a re-authorization attempt is still a permanent error.
    client = build_schwab_client(config, store_path, guard_hook)

    outcome = _renew(client, store_path, trigger_detail="explicit_command")
    print(outcome.to_json())

    # Map outcome to exit code per contracts/cli.md
    exit_codes = {
        "renewed": 0,
        "not_needed": 0,
        "reauth_required": 3,
        "transient_failure": 7,
    }
    sys.exit(exit_codes.get(outcome.outcome, 1))


def package_version() -> str:
    """Version of the installed package — single source: package metadata.

    Visible in ``schwab-mcp --help`` so a recipient can report exactly
    what they run (FR-005).  No duplicate version constant: the value is
    stamped into the metadata at install time from ``pyproject.toml``.
    """
    try:
        return distribution_version("schwab-mcp")
    except PackageNotFoundError:
        return "unknown"


def _run_serve_command() -> None:
    """Run the ``serve`` command body.

    The late import keeps the server module loadable after the CLI has
    been patched (same reason the import sat inside the ``elif`` arm).
    """
    from schwab_mcp.server import run_serve

    run_serve()


def _run_command(runner: Callable[[], None]) -> None:
    """Run a CLI command body with the shared error mapping (TD-006).

    Replaces the ``try / except AuthError / except Exception / else
    sys.exit(0)`` block previously duplicated across the ``renew``,
    ``auth-status`` and ``serve`` arms. ``SystemExit`` raised by a
    runner that maps its own outcome to an exit code (``run_renew``)
    propagates untouched (``SystemExit`` is not an ``Exception``).
    """
    try:
        runner()
    except AuthError as e:
        print(e.message, file=sys.stderr)
        sys.exit(e.exit_code)
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        sys.exit(1)
    else:
        sys.exit(0)


def _run_auth_command(runner: Callable[[], None]) -> None:
    """Run the ``auth`` command body.

    Kept separate from :func:`_run_command` (TD-006): ``auth`` handles
    :class:`ConcurrentAuthError` — with an audit event — and
    :class:`AuthorizationCancelledError` specially, and deliberately has
    no generic ``except Exception`` clause; folding it into the shared
    mapping would change the auth contract (``contracts/cli.md``).
    """
    try:
        runner()
    except ConcurrentAuthError:
        auth_event(
            "auth_failure", "refused_concurrent",
            "another auth already running",
        )
        print(ConcurrentAuthError.message, file=sys.stderr)
        sys.exit(ConcurrentAuthError.exit_code)
    except AuthorizationCancelledError:
        print(AuthorizationCancelledError.message, file=sys.stderr)
        sys.exit(AuthorizationCancelledError.exit_code)
    except AuthError as e:
        print(e.message, file=sys.stderr)
        sys.exit(e.exit_code)
    else:
        sys.exit(0)


#: Command dispatch table (TD-006): one entry per ``schwab-mcp``
#: subcommand; each value runs the command with the appropriate error
#: mapping. Adding a command is a table entry, not a new ``elif`` arm.
_COMMAND_RUNNERS: dict[str, Callable[[], None]] = {
    "auth": partial(_run_auth_command, run_auth),
    "renew": partial(_run_command, run_renew),
    "auth-status": partial(_run_command, run_auth_status),
    "serve": partial(_run_command, _run_serve_command),
}


def main(argv: list[str] | None = None) -> None:
    """Main entry point for the ``schwab-mcp`` console script."""
    # Install redaction filter on root and schwabdev loggers at startup.
    install_redaction_filter(logging.root)  # root logger
    install_redaction_filter(logging.getLogger("Schwabdev"))

    parser = argparse.ArgumentParser(
        prog="schwab-mcp",
        description=f"schwab-mcp {package_version()} — local stdio MCP server for Schwab account data",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("auth", help="Authorize Schwab API access")
    subparsers.add_parser("renew", help="Renew the access credential (non-interactive)")
    subparsers.add_parser(
        "auth-status", help="Show authentication status (local read, no network)"
    )
    subparsers.add_parser("serve", help="Start the stdio MCP server")
    args = parser.parse_args(argv)

    runner = _COMMAND_RUNNERS.get(args.command)
    if runner is None:
        parser.print_help()
        sys.exit(1)
    runner()


if __name__ == "__main__":
    main()