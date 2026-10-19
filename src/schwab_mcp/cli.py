"""schwab-mcp CLI entry point (console_scripts)."""

from __future__ import annotations

import argparse
import sys
import webbrowser

import schwabdev  # Module-level import so monkeypatch can patch schwabdev.Client

from schwab_mcp.config import load_config
from schwab_mcp.errors import (
    AuthError,
    AuthorizationCancelledError,
    ConcurrentAuthError,
    TokenStoreCorruptedError,
)
from schwab_mcp.log import auth_event, install_redaction_filter
from schwab_mcp.tokens import AuthLock, enforce_permissions, peek_store, peek_store_status


def _build_auth_url(app_key: str, callback_url: str) -> str:
    """Build the Schwab OAuth authorization URL."""
    import urllib.parse

    return (
        "https://api.schwabapi.com/v1/oauth/authorize"
        f"?client_id={urllib.parse.quote(app_key)}"
        f"&redirect_uri={urllib.parse.quote(callback_url)}"
    )


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

    # FR-009: A corrupted store must be detected BEFORE the schwabdev
    # client is constructed — the real client's ``CREATE TABLE`` raises a
    # raw ``sqlite3.DatabaseError`` on a non-SQLite store file.
    if peek_store_status(config.token_db) == "corrupted":
        raise TokenStoreCorruptedError(
            detail="Store treated as absent; run `schwab-mcp auth`"
        )

    lock_path = config.token_db
    with AuthLock(lock_path):
        auth_event("auth_start", "initiated", "browser flow requested")

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
        # tokens before returning.
        schwabdev.Client(
            config.app_key,
            config.app_secret,
            config.callback_url,
            tokens_db=config.token_db,
            call_on_auth=counted_hook,
            open_browser_for_auth=False,
        )

        # If the client never ran the interactive flow (e.g. inert test
        # stubs) and the store is still empty, invoke the hook manually so
        # the URL is printed and the user is prompted.
        if not peek_store(config.token_db) and hook_calls == 0:
            auth_url = _build_auth_url(config.app_key, config.callback_url)
            counted_hook(auth_url)

        # Success is determined by the STORE, never by the pasted string
        # or by TTY state (FR-002, US1/AC1): schwabdev writes the token
        # set only after a successful code exchange.
        if not peek_store(config.token_db):
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

        # Enforce restrictive permissions on the freshly stored token set.
        enforce_permissions(config.token_db)

        print("Authorization successful. Schwab API access is configured.")
        auth_event("auth_success", "ok", "token set stored")


def main(argv: list[str] | None = None) -> None:
    """Main entry point for the ``schwab-mcp`` console script."""
    # Install redaction filter on root and schwabdev loggers at startup.
    install_redaction_filter(__import__("logging").root)  # root logger
    install_redaction_filter(__import__("logging").getLogger("Schwabdev"))

    parser = argparse.ArgumentParser(prog="schwab-mcp")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("auth", help="Authorize Schwab API access")
    subparsers.add_parser("serve", help="Start the stdio MCP server")
    args = parser.parse_args(argv)

    if args.command == "auth":
        try:
            run_auth()
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
    elif args.command == "serve":
        from schwab_mcp.server import run_serve
        try:
            run_serve()
        except AuthError as e:
            print(e.message, file=sys.stderr)
            sys.exit(e.exit_code)
        except Exception as exc:
            print(f"Unexpected error: {exc}", file=sys.stderr)
            sys.exit(1)
        else:
            sys.exit(0)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()