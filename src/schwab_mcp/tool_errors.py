"""Shared tool-boundary error mapping and result envelopes.

Two pieces of the error taxonomy live here so every tool module consumes
one implementation (bugs domain-errors-swallowed, td-004):

- :func:`raise_classified_tool_error` — domain exceptions crossing an MCP
  tool boundary must surface as the MCP SDK's ``ToolError`` with an
  actionable, classified message — never as a raw exception.  The SDK
  wraps any non-``ToolError`` into
  ``UnexpectedToolError("Error executing tool <name>")`` whose message is
  all the client sees (the original only reaches stderr), so the
  actionable taxonomy message would be lost.
- the structured result-envelope builders (``validation_error``,
  ``provider_unreachable``, ``reauth_needed``, ``history_unavailable``)
  that orchestrations return for expected failures.  ``symbol`` is
  optional: single-symbol tools (``price_history``) name the offending
  symbol in the envelope, multi-symbol tools (``quotes``) omit the key
  entirely (contracts/mcp-tools.md §3).
"""

from __future__ import annotations

from typing import Any, NoReturn

from schwab_mcp.errors import (
    ConnectivityError,
    ReauthorizationRequiredError,
)


def raise_classified_tool_error(exc: Exception) -> NoReturn:
    """Raise the MCP ``ToolError`` that *exc* must surface as.

    The client-visible prefix distinguishes the remediation class so MCP
    clients can tell connectivity/retryable from auth-required from a bad
    request:

    - ``ReauthorizationRequiredError`` → ``reauth_needed: <message>``
    - ``ConnectivityError`` → ``provider_unreachable: <message>``
    - any other domain/validation exception → ``<message>`` unchanged
      (same shape the validation path has always surfaced).

    The original exception is preserved as ``__cause__``.
    """
    from mcp.server.mcpserver.exceptions import ToolError

    if isinstance(exc, ReauthorizationRequiredError):
        raise ToolError(f"reauth_needed: {exc}") from exc
    if isinstance(exc, ConnectivityError):
        raise ToolError(f"provider_unreachable: {exc}") from exc
    raise ToolError(str(exc)) from exc


# =============================================================================
# Result-envelope builders (bug td-004: one implementation per envelope)
# =============================================================================


def validation_error(detail: str, symbol: str | None = None, **extra: Any) -> dict:
    """The ``validation_error`` envelope: request rejected before any upcall.

    *symbol* is included only when given (``price_history`` names the
    offending symbol, ``quotes`` omits the key); *extra* keys follow the
    fixed fields (pinned order: outcome, detail, retryable, symbol, extra).
    """
    envelope: dict[str, Any] = {
        "outcome": "validation_error",
        "detail": detail,
        "retryable": False,
    }
    if symbol is not None:
        envelope["symbol"] = symbol
    envelope.update(extra)
    return envelope


def provider_unreachable(
    detail: str = "provider_unreachable", symbol: str | None = None
) -> dict:
    """The ``provider_unreachable`` envelope: transient source failure."""
    envelope: dict[str, Any] = {
        "outcome": "provider_unreachable",
        "detail": detail,
        "retryable": True,
    }
    if symbol is not None:
        envelope["symbol"] = symbol
    return envelope


def reauth_needed(symbol: str | None = None) -> dict:
    """The ``reauth_needed`` envelope: tokens expired beyond recovery."""
    envelope: dict[str, Any] = {
        "outcome": "reauth_needed",
        "detail": "reauth_needed",
        "retryable": False,
    }
    if symbol is not None:
        envelope["symbol"] = symbol
    return envelope


def history_unavailable(symbol: str) -> dict:
    """The ``history_unavailable`` envelope: the source returned no candles.

    Single-symbol tool envelope (``price_history``): *symbol* is required —
    the error must name the offending symbol (FR-008).
    """
    return {
        "outcome": "history_unavailable",
        "detail": "source_returned_no_candles",
        "retryable": False,
        "symbol": symbol,
    }