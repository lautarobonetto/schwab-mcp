"""Shared tool-boundary error mapping (bug domain-errors-swallowed).

Domain exceptions crossing an MCP tool boundary must surface as the MCP
SDK's ``ToolError`` with an actionable, classified message — never as a raw
exception.  The SDK wraps any non-``ToolError`` into
``UnexpectedToolError("Error executing tool <name>")`` whose message is all
the client sees (the original only reaches stderr), so the actionable
taxonomy message would be lost.
"""

from __future__ import annotations

from typing import NoReturn

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