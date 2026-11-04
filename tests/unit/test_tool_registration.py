"""Unit tests for MCP tool registration (TD-006 — DRY registration).

Pins the contract that the six tool registrations previously expressed
through hand-written boilerplate in ``schwab_mcp.server._register_tools``:

- exactly the six documented tools are registered;
- no tool's advertised input schema exposes the bound ``client``
  parameter (regression guard for the ``functools.wraps``/``__wrapped__``
  schema leak — ``partial`` is the only safe binding mechanism);
- each tool's description survives refactors byte-for-byte (agent-facing
  contract text mirrored in ``docs/tools.md``);
- the bound client is actually passed to the underlying tool function.

References
----------
- .specify/bugs/td-006-registration-cli-dry/assessment.md
"""

from __future__ import annotations

import asyncio

import pytest
from mcp.server import MCPServer

EXPECTED_DESCRIPTIONS: dict[str, str] = {
    "get_open_positions": (
        "Fetch all open positions across all linked accounts. "
        "Returns the curated set of metadata per position; "
        "use extended=true for full provider passthrough."
    ),
    "get_transaction_history": (
        "Retrieve transaction history for a date range across all "
        "linked accounts. Returns structured movements with outcome "
        "classification; use extended=true for full provider passthrough."
    ),
    "get_option_chain": (
        "Extract the option chain of an underlying with bounding "
        "filters (strikes per side, option type, target delta, max DTE). "
        "Returns the full curated chain in one invocation with all "
        "greeks and technical values; use extended=true for full "
        "provider passthrough."
    ),
    "get_quotes": (
        "Fetch current quotes for 1..20 symbols (equity/ETF, index, or "
        "option contract) in one invocation: last price, bid/ask, "
        "volume, net change, freshness (realtime/delayed/closed) and "
        "last-trade time. Use extended=true for full provider "
        "passthrough."
    ),
    "get_price_history": (
        "Fetch OHLCV candles for ONE symbol (equity/ETF or index) at "
        "5m/15m/30m/1h/daily/weekly with a named period preset "
        "(default daily, 1 month; at most 260 candles per invocation). "
        "Candles are chronological with epoch-ms timestamps; the "
        "still-forming candle is marked in_progress. Use "
        "extended_hours=true for intraday pre/post-market data and "
        "extended=true for full provider passthrough."
    ),
    "get_option_expiration_chain": (
        "List the upcoming option expirations of ONE underlying in a "
        "single cheap call: expiration date, DTE (calendar days) and "
        "settlement type, inside the get_option_chain DTE ceiling "
        "(dte_max >= 1, default 60). No strikes, quotes, or greeks; "
        "use extended=true for full provider passthrough."
    ),
}


class _RecordingClient:
    """Client stand-in that records every attribute access / call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str):
        def _record(*args: object, **kwargs: object) -> dict:
            self.calls.append((name, args, kwargs))
            return {}

        return _record


def _build_server(client: object) -> MCPServer:
    from schwab_mcp.server import _register_tools

    mcp = MCPServer("test")
    _register_tools(mcp, client)
    return mcp


class TestToolRegistration:
    """The six-tool registration contract (TD-006)."""

    def test_exactly_six_documented_tools_registered(self) -> None:
        mcp = _build_server(_RecordingClient())
        registered = set(mcp._tool_manager._tools)
        assert registered == set(EXPECTED_DESCRIPTIONS)

    def test_schemas_do_not_expose_client(self) -> None:
        """No tool schema may contain the bound ``client`` parameter.

        Guards against a ``functools.wraps``-style refactor: ``wraps``
        copies ``__wrapped__`` and ``inspect.signature`` follows it,
        which would leak ``client`` into the advertised schema.
        """
        mcp = _build_server(_RecordingClient())
        for name, tool in mcp._tool_manager._tools.items():
            properties = tool.parameters.get("properties", {})
            assert "client" not in properties, (
                f"{name} schema exposes the bound client parameter: "
                f"{sorted(properties)}"
            )

    def test_descriptions_survive_byte_for_byte(self) -> None:
        """Descriptions are agent-facing contract text; a refactor must
        not drift them (docs/tools.md parity)."""
        mcp = _build_server(_RecordingClient())
        for name, expected in EXPECTED_DESCRIPTIONS.items():
            tool = mcp._tool_manager._tools[name]
            assert tool.description == expected, (
                f"{name} description drifted from the documented text"
            )

    def test_bound_client_is_passed_to_tool_function(self) -> None:
        """Registration must bind the client so a tool invocation
        reaches the provider layer through it."""
        client = _RecordingClient()
        mcp = _build_server(client)
        try:
            asyncio.run(mcp.call_tool("get_open_positions", {}))
        except Exception:
            pass  # downstream result-shaping may fail on a fake payload
        assert client.calls, (
            "tool invocation never reached the bound client"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
