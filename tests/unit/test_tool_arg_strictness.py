"""Regression tests for bug ``option-chain-dte-filter`` (2026-11-03).

The MCP SDK validates tool arguments against a Pydantic model built with
the default ``extra='ignore'`` behaviour, so a misspelled or hallucinated
argument — e.g. ``expiration_date`` passed to ``get_option_chain``, which
has no such parameter — was silently dropped and the tool answered a
*different* question with ``outcome="ok"``.  Every tool registered
through ``schwab_mcp.server`` must instead reject unknown arguments with
a tool error naming the offending argument, and the advertised input
schema must set ``additionalProperties: false`` so conforming clients
reject the call before it is sent.

References
----------
- .specify/bugs/option-chain-dte-filter/assessment.md
"""

from __future__ import annotations

import asyncio
import json

import pytest

from mcp.server import MCPServer


# =============================================================================
# Registration fixtures
# =============================================================================


#: One hallucinated argument name per registered tool (the kind of
#: parameter a caller may wrongly extrapolate from the provider API).
BOGUS_ARGUMENTS: dict[str, str] = {
    "get_open_positions": "expiration_date",
    "get_transaction_history": "account_id",
    "get_option_chain": "expiration_date",
    "get_quotes": "expiration_date",
    "get_price_history": "expiration_date",
    "get_option_expiration_chain": "strike",
}

#: Valid required arguments per tool — enough to pass schema validation
#: so the only question left is how unknown arguments are handled.
VALID_ARGUMENTS: dict[str, dict] = {
    "get_open_positions": {},
    "get_transaction_history": {
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
    },
    "get_option_chain": {"symbol": "LLY"},
    "get_quotes": {"symbols": "SPY"},
    "get_price_history": {"symbol": "SPY"},
    "get_option_expiration_chain": {"symbol": "LLY"},
}


class _NeverCalledClient:
    """Client stand-in that fails loudly on any provider call attempt.

    Argument validation must happen *before* any upcall, so a hardened
    registration never reaches this object.  If a tool body does run
    (pre-fix behaviour), this makes the failure deterministic and
    network-free.
    """

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"unexpected provider call: {name}")


def _build_server() -> MCPServer:
    """Build a server with the real production tool registrations."""
    from schwab_mcp.server import _register_tools

    mcp = MCPServer("test")
    _register_tools(mcp, _NeverCalledClient())
    return mcp


def _call(mcp: MCPServer, name: str, arguments: dict) -> object:
    return asyncio.run(mcp.call_tool(name, arguments))


# =============================================================================
# 1. Unknown arguments are rejected loudly (the regression)
# =============================================================================


class TestUnknownArgumentsRejected:
    """Every registered tool must reject unknown arguments with an error
    that names the offending argument (bug option-chain-dte-filter)."""

    def test_unknown_argument_rejected_on_every_tool(self) -> None:
        """For each registered tool, an unknown argument produces a tool
        error whose message names the argument — never a silent drop."""
        mcp = _build_server()
        for name, bogus in BOGUS_ARGUMENTS.items():
            arguments = dict(VALID_ARGUMENTS[name])
            arguments[bogus] = "x"
            with pytest.raises(Exception, match=bogus):
                _call(mcp, name, arguments)

    def test_reported_expiration_date_call_is_rejected(self) -> None:
        """The exact call shape from the bug report —
        ``get_option_chain {"symbol":"LLY","expiration_date":"2027-01-15"}`` —
        must fail loudly instead of returning ``ok`` without the date."""
        mcp = _build_server()
        with pytest.raises(Exception, match="expiration_date"):
            _call(
                mcp,
                "get_option_chain",
                {"symbol": "LLY", "expiration_date": "2027-01-15"},
            )

    def test_rejection_happens_before_any_provider_call(self) -> None:
        """The rejection must come from argument validation, not from a
        provider failure — the never-called client is never touched."""
        mcp = _build_server()
        with pytest.raises(Exception) as excinfo:
            _call(mcp, "get_quotes", {"symbols": "SPY", "unexpected_flag": True})
        message = str(excinfo.value)
        assert "unexpected_flag" in message
        assert "unexpected provider call" not in message


# =============================================================================
# 2. Known arguments are still accepted (no over-rejection)
# =============================================================================


class TestKnownArgumentsStillAccepted:
    """Hardening must not reject legitimate arguments."""

    def test_valid_arguments_still_reach_the_tool(self) -> None:
        """``get_quotes`` with a valid (validation-failing) ``symbols``
        value reaches the tool body and returns its structured
        ``validation_error`` envelope — proving known arguments pass the
        hardened schema unchanged."""
        mcp = _build_server()
        result = _call(mcp, "get_quotes", {"symbols": ""})
        assert not result.is_error, f"Unexpected tool error: {result.content}"
        payload = json.loads(result.content[0].text)
        assert payload["outcome"] == "validation_error"
        assert payload["detail"] == "empty_symbol_list"

    def test_missing_required_argument_still_rejected(self) -> None:
        """A missing required argument is still a validation error naming
        that argument (pre-existing SDK behaviour must be preserved)."""
        mcp = _build_server()
        with pytest.raises(Exception, match="symbol"):
            _call(mcp, "get_option_chain", {})


# =============================================================================
# 3. Advertised input schema forbids additional properties
# =============================================================================


class TestAdvertisedSchema:
    """Conforming clients must be able to reject unknown arguments
    before the call is sent."""

    def test_input_schema_forbids_additional_properties(self) -> None:
        """Every registered tool's input schema sets
        ``additionalProperties: false``."""
        tools = asyncio.run(_build_server().list_tools())
        assert len(tools) == len(BOGUS_ARGUMENTS), (
            f"Expected {len(BOGUS_ARGUMENTS)} registered tools, got "
            f"{[t.name for t in tools]}"
        )
        for tool in tools:
            assert tool.input_schema.get("additionalProperties") is False, (
                f"Tool {tool.name} input schema does not forbid "
                f"additional properties: {tool.input_schema}"
            )