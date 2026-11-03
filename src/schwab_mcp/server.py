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
from pydantic import ConfigDict

from schwab_mcp.config import Config, load_config
from schwab_mcp.errors import (
    AuthError,
    ConnectivityError,
    ReauthorizationRequiredError,
    TokenStoreCorruptedError,
)
from schwab_mcp.log import auth_event, install_redaction_filter
from schwab_mcp.provider import response_json
from schwab_mcp.schwabdev_compat import install_trailing_slash_callback_support
from schwab_mcp.tokens import peek_store_status, retry_call

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


def register_tool(mcp: MCPServer, fn: Any, *, name: str, description: str) -> None:
    """Register *fn* as an MCP tool that rejects unknown arguments.

    Bug option-chain-dte-filter (2026-11-03): the MCP SDK validates tool
    arguments against a Pydantic model built with the default
    ``extra='ignore'`` behaviour, so a misspelled or hallucinated
    argument — e.g. ``expiration_date`` passed to ``get_option_chain``,
    which has no such parameter — was silently dropped and the tool
    answered a *different* question with ``outcome="ok"``.  Two touch
    points make the rejection loud:

    - server-side: the SDK's per-tool argument model is rebuilt with
      ``extra='forbid'`` so validation rejects unknown keys with a tool
      error naming the offending argument;
    - schema-side: the advertised input schema sets
      ``additionalProperties: false`` so conforming clients reject the
      call before it is sent.

    The SDK exposes no public switch for either setting; the mutation
    covers the SDK's own registration artifacts and is pinned by
    ``tests/unit/test_tool_arg_strictness.py``.
    """
    mcp.add_tool(fn, name=name, description=description)
    # The tool manager keeps registered tools by name; no public accessor
    # returns the full Tool object with its argument model.
    tool = mcp._tool_manager._tools[name]
    arg_model = tool.fn_metadata.arg_model
    # Pydantic v2 only honours a post-hoc model_config change after a
    # forced rebuild of the validation schema.
    arg_model.model_config = ConfigDict(extra="forbid")
    arg_model.model_rebuild(force=True)
    tool.parameters["additionalProperties"] = False


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
    guard_hook = _build_serve_guard_hook()

    # Same relaxation as ``auth``: preserve a portal-required trailing
    # slash in the callback URL (literal redirect_uri comparison).
    install_trailing_slash_callback_support()

    from schwab_mcp.client import (  # noqa: PLC0415 — late import so CLI can patch
        build_schwab_client,
    )

    try:
        client = build_schwab_client(config, store_path, guard_hook)
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
    #
    #    Bug renew-phantom-success: schwabdev returns requests.Response
    #    objects and an HTTP 401 does NOT raise, so the response must be
    #    classified explicitly through the shared ``provider.response_json``
    #    unwrapper before the call can count as a successful validation.
    # ------------------------------------------------------------------
    auth_event("renew_start", "initiated", detail="margin_trigger")
    try:
        response = retry_call(client.linked_accounts, retries=1)
        response_json(response)
    except ReauthorizationRequiredError:
        auth_event(
            "renewal_failure",
            "reauth_required",
            detail="run: schwab-mcp auth",
        )
        raise
    except ConnectivityError:
        auth_event(
            "renewal_failure",
            "connectivity",
            detail="retries exhausted",
        )
        raise

    auth_event("renewal_success", "ok", detail="access token renewed")

    # ------------------------------------------------------------------
    # 5. Register tools and connect MCPServer stdio transport
    # ------------------------------------------------------------------
    mcp = MCPServer("schwab-mcp")
    _register_tools(mcp, client)

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


def _register_tools(mcp: MCPServer, client: Any) -> None:
    """Register every agent-facing MCP tool on *mcp*.

    Extracted from ``run_serve`` (bug option-chain-dte-filter) so tool
    registration — and the strict unknown-argument hardening applied by
    :func:`register_tool` — is unit-testable without a live session.
    Every registration MUST go through :func:`register_tool`; a plain
    ``mcp.add_tool`` call would silently ignore unknown arguments.
    """
    # Register the get_open_positions tool (003-list-open-positions).
    # The client is bound via a closure so the MCP input schema only
    # exposes the ``extended`` parameter.
    from schwab_mcp.positions import get_open_positions as _get_open_positions

    def _get_open_positions_wrapper(extended: bool = False) -> object:
        return _get_open_positions(client, extended=extended)

    _get_open_positions_wrapper.__name__ = "get_open_positions"
    _get_open_positions_wrapper.__qualname__ = "get_open_positions"
    register_tool(mcp,
        _get_open_positions_wrapper,
        name="get_open_positions",
        description=(
            "Fetch all open positions across all linked accounts. "
            "Returns the curated set of metadata per position; "
            "use extended=true for full provider passthrough."
        ),
    )

    # Register the get_transaction_history tool (006-transaction-history).
    from schwab_mcp.transactions import (
        get_transaction_history_tool as _get_transaction_history,
    )

    def _get_transaction_history_wrapper(
        start_date: str,
        end_date: str,
        symbol: str | None = None,
        extended: bool = False,
        offset: int = 0,
    ) -> object:
        return _get_transaction_history(
            client,
            start_date=start_date,
            end_date=end_date,
            symbol=symbol,
            extended=extended,
            offset=offset,
        )

    _get_transaction_history_wrapper.__name__ = "get_transaction_history"
    _get_transaction_history_wrapper.__qualname__ = "get_transaction_history"
    register_tool(mcp,
        _get_transaction_history_wrapper,
        name="get_transaction_history",
        description=(
            "Retrieve transaction history for a date range across all "
            "linked accounts. Returns structured movements with outcome "
            "classification; use extended=true for full provider passthrough."
        ),
    )

    # Register the get_option_chain tool (008-extract-option-chain).
    from schwab_mcp.options_chain import (
        get_option_chain_tool as _get_option_chain,
    )

    def _get_option_chain_wrapper(
        symbol: str,
        max_strikes: int = 50,
        option_type: str = "both",
        delta_target: float | None = None,
        dte_max: int | None = None,
        extended: bool = False,
    ) -> object:
        return _get_option_chain(
            client,
            symbol=symbol,
            max_strikes=max_strikes,
            option_type=option_type,
            delta_target=delta_target,
            dte_max=dte_max,
            extended=extended,
        )

    _get_option_chain_wrapper.__name__ = "get_option_chain"
    _get_option_chain_wrapper.__qualname__ = "get_option_chain"
    register_tool(mcp,
        _get_option_chain_wrapper,
        name="get_option_chain",
        description=(
            "Extract the option chain of an underlying with bounding "
            "filters (strikes per side, option type, target delta, max DTE). "
            "Returns the full curated chain in one invocation with all "
            "greeks and technical values; use extended=true for full "
            "provider passthrough."
        ),
    )

    # Register the get_quotes tool (010-real-time-quotes).
    from schwab_mcp.quotes import get_quotes_tool as _get_quotes

    def _get_quotes_wrapper(
        symbols: str | list[str],
        extended: bool = False,
    ) -> object:
        return _get_quotes(client, symbols=symbols, extended=extended)

    _get_quotes_wrapper.__name__ = "get_quotes"
    _get_quotes_wrapper.__qualname__ = "get_quotes"
    register_tool(mcp,
        _get_quotes_wrapper,
        name="get_quotes",
        description=(
            "Fetch current quotes for 1..20 symbols (equity/ETF, index, or "
            "option contract) in one invocation: last price, bid/ask, "
            "volume, net change, freshness (realtime/delayed/closed) and "
            "last-trade time. Use extended=true for full provider "
            "passthrough."
        ),
    )

    # Register the get_price_history tool (011-price-history-ohlcv).
    from schwab_mcp.price_history import get_price_history_tool as _get_price_history

    def _get_price_history_wrapper(
        symbol: str,
        frequency: str = "daily",
        period: str = "1m",
        extended_hours: bool = False,
        extended: bool = False,
    ) -> object:
        return _get_price_history(
            client,
            symbol=symbol,
            frequency=frequency,
            period=period,
            extended_hours=extended_hours,
            extended=extended,
        )

    _get_price_history_wrapper.__name__ = "get_price_history"
    _get_price_history_wrapper.__qualname__ = "get_price_history"
    register_tool(mcp,
        _get_price_history_wrapper,
        name="get_price_history",
        description=(
            "Fetch OHLCV candles for ONE symbol (equity/ETF or index) at "
            "5m/15m/30m/1h/daily/weekly with a named period preset "
            "(default daily, 1 month; at most 260 candles per invocation). "
            "Candles are chronological with epoch-ms timestamps; the "
            "still-forming candle is marked in_progress. Use "
            "extended_hours=true for intraday pre/post-market data and "
            "extended=true for full provider passthrough."
        ),
    )

    # Register the get_option_expiration_chain tool (012-option-expiration-list).
    from schwab_mcp.options_chain import (
        get_option_expiration_chain_tool as _get_option_expiration_chain,
    )

    def _get_option_expiration_chain_wrapper(
        symbol: str,
        dte_max: int | None = None,
        extended: bool = False,
    ) -> object:
        return _get_option_expiration_chain(
            client,
            symbol=symbol,
            dte_max=dte_max,
            extended=extended,
        )

    _get_option_expiration_chain_wrapper.__name__ = "get_option_expiration_chain"
    _get_option_expiration_chain_wrapper.__qualname__ = "get_option_expiration_chain"
    register_tool(mcp,
        _get_option_expiration_chain_wrapper,
        name="get_option_expiration_chain",
        description=(
            "List the upcoming option expirations of ONE underlying in a "
            "single cheap call: expiration date, DTE (calendar days) and "
            "settlement type, inside the get_option_chain DTE ceiling "
            "(dte_max >= 1, default 60). No strikes, quotes, or greeks; "
            "use extended=true for full provider passthrough."
        ),
    )


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