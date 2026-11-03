"""Bug domain-errors-swallowed: auth-taxonomy domain errors must reach the
MCP client as classified ``ToolError`` — never as a raw exception, which the
MCP SDK wraps into the opaque ``UnexpectedToolError("Error executing tool
<name>")`` whose message is all the client sees.

Discriminating assertions: the exact type must be ``ToolError`` (the SDK's
``UnexpectedToolError`` subclasses it, so ``pytest.raises(ToolError)`` alone
cannot distinguish a deliberate conversion from an SDK crash wrapper), and
the message must carry the classification prefix so clients can tell
connectivity/retryable from auth-required from bad request.
"""

from __future__ import annotations

import pytest

from schwab_mcp.errors import ConnectivityError, ReauthorizationRequiredError

# =============================================================================
# Shared helper: raise_classified_tool_error
# =============================================================================


class TestClassifiedToolErrorHelper:
    def test_connectivity_error_gets_provider_unreachable_prefix(self) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        from schwab_mcp.tool_errors import raise_classified_tool_error

        original = ConnectivityError(detail="Schwab API unreachable after retry")
        with pytest.raises(ToolError) as excinfo:
            raise_classified_tool_error(original)
        assert type(excinfo.value) is ToolError
        assert excinfo.value.__cause__ is original
        assert str(excinfo.value).startswith("provider_unreachable: ")
        assert "unreachable after retry" in str(excinfo.value)

    def test_reauthorization_error_gets_reauth_needed_prefix(self) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        from schwab_mcp.tool_errors import raise_classified_tool_error

        original = ReauthorizationRequiredError(detail="run: schwab-mcp auth")
        with pytest.raises(ToolError) as excinfo:
            raise_classified_tool_error(original)
        assert type(excinfo.value) is ToolError
        assert excinfo.value.__cause__ is original
        assert str(excinfo.value).startswith("reauth_needed: ")
        assert "schwab-mcp auth" in str(excinfo.value)

    def test_other_domain_error_passes_message_without_prefix(self) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        from schwab_mcp.tool_errors import raise_classified_tool_error

        original = ValueError("max_strikes must be >= 1")
        with pytest.raises(ToolError) as excinfo:
            raise_classified_tool_error(original)
        assert type(excinfo.value) is ToolError
        assert str(excinfo.value) == "max_strikes must be >= 1"


# =============================================================================
# Tool wrappers: the taxonomy errors must not leak as raw exceptions
# =============================================================================

_TIMEOUT = ConnectivityError(detail="Schwab API unreachable after retry")
_EXPIRED = ReauthorizationRequiredError(detail="run: schwab-mcp auth")


class TestOptionChainToolClassifiedErrors:
    @pytest.mark.parametrize(
        ("error", "prefix"),
        [
            (_TIMEOUT, "provider_unreachable"),
            (_EXPIRED, "reauth_needed"),
        ],
        ids=["connectivity", "reauth"],
    )
    def test_taxonomy_errors_become_classified_tool_error(
        self, monkeypatch, error, prefix
    ) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        import schwab_mcp.options_chain as oc

        def raiser(*args, **kwargs):
            raise error

        monkeypatch.setattr(oc, "get_option_chain", raiser)
        with pytest.raises(ToolError) as excinfo:
            oc.get_option_chain_tool(None, "SPY")
        assert type(excinfo.value) is ToolError
        assert str(excinfo.value).startswith(f"{prefix}: ")

    def test_connectivity_and_reauth_are_distinguishable(self, monkeypatch) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        import schwab_mcp.options_chain as oc

        def raise_connectivity(*args, **kwargs):
            raise _TIMEOUT

        def raise_reauth(*args, **kwargs):
            raise _EXPIRED

        monkeypatch.setattr(oc, "get_option_chain", raise_connectivity)
        with pytest.raises(ToolError) as conn_exc:
            oc.get_option_chain_tool(None, "SPY")
        monkeypatch.setattr(oc, "get_option_chain", raise_reauth)
        with pytest.raises(ToolError) as reauth_exc:
            oc.get_option_chain_tool(None, "SPY")
        assert str(conn_exc.value).startswith("provider_unreachable: ")
        assert str(reauth_exc.value).startswith("reauth_needed: ")


class TestOptionExpirationChainToolClassifiedErrors:
    @pytest.mark.parametrize(
        ("error", "prefix"),
        [
            (_TIMEOUT, "provider_unreachable"),
            (_EXPIRED, "reauth_needed"),
        ],
        ids=["connectivity", "reauth"],
    )
    def test_taxonomy_errors_become_classified_tool_error(
        self, monkeypatch, error, prefix
    ) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        import schwab_mcp.options_chain as oc

        def raiser(*args, **kwargs):
            raise error

        monkeypatch.setattr(oc, "get_option_expiration_chain", raiser)
        with pytest.raises(ToolError) as excinfo:
            oc.get_option_expiration_chain_tool(None, "SPY")
        assert type(excinfo.value) is ToolError
        assert str(excinfo.value).startswith(f"{prefix}: ")


class TestTransactionHistoryToolClassifiedErrors:
    @pytest.mark.parametrize(
        ("error", "prefix"),
        [
            (_TIMEOUT, "provider_unreachable"),
            (_EXPIRED, "reauth_needed"),
        ],
        ids=["connectivity", "reauth"],
    )
    def test_taxonomy_errors_become_classified_tool_error(
        self, monkeypatch, error, prefix
    ) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        import schwab_mcp.transactions as tx

        def raiser(*args, **kwargs):
            raise error

        monkeypatch.setattr(tx, "get_transaction_history", raiser)
        with pytest.raises(ToolError) as excinfo:
            tx.get_transaction_history_tool(None, "2026-01-01", "2026-01-31")
        assert type(excinfo.value) is ToolError
        assert str(excinfo.value).startswith(f"{prefix}: ")