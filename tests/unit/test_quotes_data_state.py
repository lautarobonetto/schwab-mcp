"""RED-phase data-state derivation tests for ``get_quotes`` (T006, US1).

TDD red-phase: ``schwab_mcp.quotes`` exposes the skeleton only, so every
test fails until T010 lands.

Pins the research D4 ladder — the freshness state is deterministic or
absent, never guessed:

1. market closed (the single per-invocation ``market_hours`` check) ->
   ``closed``, regardless of ``quoteType``/``realtime``;
2. market open -> ``realtime`` when the provider marks the quote live
   (``quoteType == "Realtime"`` per D4, and the live payload's
   authoritative ``realtime`` flag — evidence captured 2026-10-27);
3. anything else (missing/other ``quoteType``, absent or false flag) ->
   ``delayed`` (conservative: never claim live when uncertain).

A market-hours failure yields a structured retryable
``provider_unreachable`` error (reauth classification for 401/403), and
the market-hours check runs exactly once per invocation — not per symbol.
"""

from __future__ import annotations

import pytest

from tests.unit.fixtures.quotes_payloads import (
    BATCH_QUOTE_PAYLOAD,
    EQUITY_QUOTE_ENTRY,
    INDEX_QUOTE_ENTRY,
    MARKET_HOURS_CLOSED_PAYLOAD,
)
from tests.unit.helpers import FakeQuotesClient, build_quote_entry, build_quotes_payload


def _state(client: FakeQuotesClient, symbols) -> str:
    from schwab_mcp.quotes import get_quotes

    result = get_quotes(client, symbols)
    assert result["outcome"] == "ok", result
    (quote,) = result["quotes"].values()
    return quote["data_state"]


# =============================================================================
# Closed market overrides everything (D4 step 1)
# =============================================================================


class TestClosedMarket:
    """``isOpen: false`` -> ``closed`` regardless of quote signals."""

    @pytest.mark.parametrize(
        "realtime,quote_type",
        [(True, "NBBO"), (True, "Realtime"), (False, "NBBO"), (None, None)],
        ids=["live-nbbo", "typed-realtime", "flag-false", "no-signals"],
    )
    def test_closed_when_market_hours_reports_closed(self, realtime, quote_type) -> None:
        entry = build_quote_entry("AAPL", realtime=realtime, quote_type=quote_type)
        client = FakeQuotesClient(
            quotes_payload={"AAPL": entry},
            market_hours_payload=MARKET_HOURS_CLOSED_PAYLOAD,
        )

        assert _state(client, "AAPL") == "closed"

    def test_closed_uses_live_weekend_capture(self) -> None:
        """The live closed-day capture (weekend 2026-10-24) drives the
        closed state for a live quote entry."""
        client = FakeQuotesClient(
            quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY},
            market_hours_payload=MARKET_HOURS_CLOSED_PAYLOAD,
        )

        assert _state(client, "AAPL") == "closed"


# =============================================================================
# Open market ladder (D4 steps 2-3)
# =============================================================================


class TestOpenMarket:
    """Open market: live signals -> ``realtime``; anything else ->
    ``delayed``."""

    def test_live_equity_flag_is_realtime(self) -> None:
        """Live shape (quoteType NBBO + ``realtime: true``) -> realtime."""
        client = FakeQuotesClient(quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY})
        assert _state(client, "AAPL") == "realtime"

    def test_live_index_flag_is_realtime(self) -> None:
        """Index entries carry no ``quoteType`` at all; the ``realtime``
        flag still determines freshness."""
        client = FakeQuotesClient(quotes_payload={"$SPX": INDEX_QUOTE_ENTRY})
        assert _state(client, "$SPX") == "realtime"

    def test_quote_type_realtime_without_flag_is_realtime(self) -> None:
        """D4 ladder: ``quoteType == "Realtime"`` -> realtime."""
        entry = build_quote_entry("AAPL", realtime=None, quote_type="Realtime")
        client = FakeQuotesClient(quotes_payload={"AAPL": entry})
        assert _state(client, "AAPL") == "realtime"

    def test_realtime_false_is_delayed(self) -> None:
        """The authoritative flag says the quote is not live -> delayed."""
        entry = build_quote_entry("AAPL", realtime=False, quote_type="NBBO")
        client = FakeQuotesClient(quotes_payload={"AAPL": entry})
        assert _state(client, "AAPL") == "delayed"

    def test_other_quote_type_is_delayed(self) -> None:
        """Any other ``quoteType`` value (e.g. 'Indicated') -> delayed."""
        entry = build_quote_entry("AAPL", realtime=None, quote_type="Indicated")
        client = FakeQuotesClient(quotes_payload={"AAPL": entry})
        assert _state(client, "AAPL") == "delayed"

    def test_missing_quote_type_and_flag_is_delayed(self) -> None:
        """Missing/unknown freshness signals -> delayed (conservative)."""
        entry = build_quote_entry("AAPL", realtime=None, quote_type=None)
        client = FakeQuotesClient(quotes_payload={"AAPL": entry})
        assert _state(client, "AAPL") == "delayed"

    def test_quote_type_realtime_wins_even_when_flag_false(self) -> None:
        """``quoteType == "Realtime"`` is an explicit live claim (D4) and
        yields ``realtime`` regardless of the flag."""
        entry = build_quote_entry("AAPL", realtime=False, quote_type="Realtime")
        client = FakeQuotesClient(quotes_payload={"AAPL": entry})
        assert _state(client, "AAPL") == "realtime"


# =============================================================================
# Market-hours failures (D4: never guess)
# =============================================================================


class TestMarketHoursFailure:
    """A failing market-hours check aborts with a structured error — the
    freshness state is never guessed."""

    @pytest.mark.parametrize("status", [500, 503, 408, 429])
    def test_market_hours_failure_status_is_provider_unreachable(self, status) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY},
            market_hours_status=status,
        )
        result = get_quotes(client, "AAPL")

        assert result["outcome"] == "provider_unreachable"
        assert result["retryable"] is True
        assert "quotes" not in result, "never a guessed or partial state"

    def test_market_hours_network_error_is_provider_unreachable(self) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY},
            market_hours_error=ConnectionError("network down"),
        )
        result = get_quotes(client, "AAPL")

        assert result["outcome"] == "provider_unreachable"
        assert result["retryable"] is True

    def test_unusable_market_hours_payload_is_provider_unreachable(self) -> None:
        """A response without any ``isOpen`` indicator is unusable:
        deterministic or absent — provider_unreachable, never guessed."""
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY},
            market_hours_payload={},
        )
        result = get_quotes(client, "AAPL")

        assert result["outcome"] == "provider_unreachable"
        assert result["retryable"] is True

    def test_market_hours_401_is_reauth_needed(self) -> None:
        """401/403 follow the shared taxonomy -> reauth_needed."""
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY},
            market_hours_status=401,
        )
        result = get_quotes(client, "AAPL")

        assert result["outcome"] == "reauth_needed"
        assert result["retryable"] is False


# =============================================================================
# One market-hours check per invocation (D4)
# =============================================================================


class TestSingleMarketHoursCheck:
    """The freshness check runs once per invocation, never per symbol."""

    def test_batch_makes_exactly_one_market_hours_call(self) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload=dict(BATCH_QUOTE_PAYLOAD))
        result = get_quotes(client, ["AAPL", "$SPX", "AAPL  261028C00345000"])

        assert result["outcome"] == "ok"
        assert len(client.market_hours_calls) == 1
        assert len(client.quotes_calls) == 1

    def test_single_symbol_makes_exactly_one_market_hours_call(self) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY})
        get_quotes(client, "AAPL")

        assert len(client.market_hours_calls) == 1
