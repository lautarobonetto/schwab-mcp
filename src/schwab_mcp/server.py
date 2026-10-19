"""Stdio MCP server startup with proactive access validation (FR-013, SC-004).

This module is headless by design — it never opens a browser, never reads
stdin beyond the MCP stdio channel, and never triggers an implicit
authorization flow (FR-001).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from mcp.server import MCPServer

from schwab_mcp.config import Config, load_config
from schwab_mcp.errors import (
    AuthError,
    ConnectivityError,
    ReauthorizationRequiredError,
    TokenStoreCorruptedError,
)
from schwab_mcp.log import auth_event, install_redaction_filter
from schwab_mcp.tokens import peek_store_status, retry_once

_logger = logging.getLogger(__name__)


def _build_serve_guard_hook() -> Any:
    """Return a ``call_on_auth`` hook that **never** starts a browser flow.

    In ``serve`` context, any attempt by schwabdev to re-authorise is a
    fatal error: the token set has expired beyond recovery or is absent.
    This hook raises :exc:`ReauthorizationRequiredError` so that the server
    exits with a clear message *before* any MCP handshake.
    """

    def guard_hook(auth_url: str) -> str:
        raise ReauthorizationRequiredError(
            detail="Token set expired or absent; run `schwab-mcp auth`"
        )

    return guard_hook


def run_serve() -> None:
    """Run the headless stdio MCP server (``schwab-mcp serve``).

    Sequence
    --------
    1. Load and validate configuration (fail-fast).
    2. Peek at the token store — absent / corrupted → exit with
       ``ReauthorizationRequiredError`` / ``TokenStoreCorruptedError``
       **before** any MCP handshake.
    3. Instantiate the schwabdev client with a guarding ``call_on_auth``
       hook that always raises.
    4. Proactively verify live access via ``linked_accounts()``
       (FR-013).  Network errors → ``ConnectivityError`` after one retry.
    5. Connect the MCPServer stdio transport and signal ready.
    """
    config = load_config()

    # ------------------------------------------------------------------
    # 2. Token-store peek (FR-009)
    # ------------------------------------------------------------------
    store_path = config.token_db
    status = peek_store_status(store_path)

    if status == "absent":
        raise ReauthorizationRequiredError(
            detail="No usable token set found; run `schwab-mcp auth`"
        )

    if status == "corrupted":
        raise TokenStoreCorruptedError(
            detail="Store treated as absent; run `schwab-mcp auth`"
        )

    # ------------------------------------------------------------------
    # 3. Instantiate schwabdev client with guard hook (FR-001)
    # ------------------------------------------------------------------
    import schwabdev  # noqa: PLC0415 — late import so CLI can patch

    guard_hook = _build_serve_guard_hook()

    try:
        client = schwabdev.Client(
            config.app_key,
            config.app_secret,
            config.callback_url,
            tokens_db=store_path,
            call_on_auth=guard_hook,
            open_browser_for_auth=False,
        )
    except ValueError as exc:
        # schwabdev validates key format and raises ValueError on malformed
        # credentials — map to InvalidConfigError per contracts/cli.md.
        from schwab_mcp.errors import InvalidConfigError as _InvalidConfigError
        raise _InvalidConfigError(
            detail=f"Fix the values in your environment: {exc}"
        ) from exc
    except Exception as exc:
        raise ReauthorizationRequiredError(
            detail=f"Client initialisation failed: {exc}"
        ) from exc

    # ------------------------------------------------------------------
    # 4. Proactive access validation (FR-013, SC-004)
    #    renewal_success is emitted ONLY after the validation outcome is
    #    known (contracts/events.md: it marks a *succeeded* refresh/
    #    validation — never before the outcome, and never for auxiliary
    #    transitions like loading the store or reaching ready state).
    # ------------------------------------------------------------------
    try:
        retry_once(client.linked_accounts)
    except ConnectivityError:
        auth_event(
            "renewal_failure",
            "connectivity",
            detail="run: schwab-mcp auth",
        )
        raise

    auth_event("renewal_success", "ok", detail="access token renewed")

    # ------------------------------------------------------------------
    # 5. Connect MCPServer stdio transport and signal ready
    # ------------------------------------------------------------------
    mcp = MCPServer("schwab-mcp")
    # This feature registers no tools (tools arrive in a later feature).

    # Run the stdio transport — this call blocks until the server exits.
    try:
        asyncio.run(mcp.run_stdio_async())
    except KeyboardInterrupt:
        pass
    except Exception:
        # A tool-level failure (renewal after ready) is surfaced to the
        # client as an error; the process does not self-restart the
        # browser flow.
        raise


if __name__ == "__main__":
    # Direct invocation: handle errors locally.
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