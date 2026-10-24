"""Regression tests for live-SDK response handling (found 2026-10-23).

Manual testing against the real ``schwabdev`` client revealed three
defects that dict-based fakes could not catch:

1. The SDK returns ``requests.Response`` objects — the orchestration must
   unwrap ``.json()`` and classify non-2xx statuses (SC-002: a valid query
   must be usable on the first attempt).
2. The real ``linked_accounts()`` payload uses ``hashValue``, not
   ``accountHash`` — the account hash extraction must accept both.
3. The SDK ``instruments()`` response is also a ``Response``; an unknown
   symbol (empty JSON list) must raise ``InstrumentNotFoundError``, and
   validation errors must reach the MCP client as actionable ``ToolError``
   messages (FR-009d / SC-005), not the SDK's generic wrapper text.

References: spec FR-004/FR-008/FR-009, contracts/mcp-tools.md.
"""

from __future__ import annotations

import json

import pytest
import requests

from schwab_mcp.transactions import (
    InstrumentNotFoundError,
    get_transaction_history,
    get_transaction_history_tool,
)


# =============================================================================
# Response-building helpers (mimic the real schwabdev client)
# =============================================================================


def _response(payload, status: int = 200) -> requests.Response:
    """Build a real ``requests.Response`` carrying a JSON *payload*."""
    r = requests.Response()
    r.status_code = status
    if payload is not None:
        r._content = json.dumps(payload).encode()
    return r


class LiveLikeClient:
    """Fake client that returns ``requests.Response`` objects, like the SDK."""

    def __init__(
        self,
        accounts: list | None = None,
        transactions_payload: dict | None = None,
        transactions_status: int = 200,
        instruments_payload=None,
    ) -> None:
        self.accounts = accounts if accounts is not None else []
        self.transactions_payload = (
            transactions_payload if transactions_payload is not None else {"transactions": []}
        )
        self.transactions_status = transactions_status
        self.instruments_payload = instruments_payload
        self.transactions_calls: list[str] = []
        # The orchestration toggles ``client._validator.enabled`` (research D2)
        self._validator = type("_Validator", (), {"enabled": True})()

    def linked_accounts(self) -> requests.Response:
        # Real payload shape: [{"hashValue": ..., "accountNumber": ...}]
        return _response(
            [{"hashValue": h, "accountNumber": f"acc-{i}"}
             for i, h in enumerate(self.accounts)]
        )

    def transactions(
        self, accountHash: str, startDate, endDate, types: str, symbol=None
    ) -> requests.Response:
        self.transactions_calls.append(accountHash)
        self.last_transactions_kwargs = {
            "accountHash": accountHash,
            "startDate": startDate,
            "endDate": endDate,
            "types": types,
            "symbol": symbol,
        }
        return _response(self.transactions_payload, status=self.transactions_status)

    def instruments(self, symbols, projection) -> requests.Response:
        self.last_instruments_kwargs = {"symbols": symbols, "projection": projection}
        return _response(self.instruments_payload)


def _tx_payload() -> dict:
    """One trade per account, provider-shaped."""
    return {
        "transactions": [
            {
                "activityId": "101",
                "type": "TRADE",
                "transactionDate": "2026-09-03T15:45:00+00:00",
                "description": "You Bought 10 shares of AAPL",
                "netAmount": -2318.9,
                "instrument": {"symbol": "AAPL", "instrumentType": "EQUITY"},
            }
        ]
    }


# =============================================================================
# 1. Response unwrapping + hashValue extraction
# =============================================================================


class TestSdkResponsesAreUnwrapped:
    def test_ok_result_from_response_objects(self) -> None:
        client = LiveLikeClient(
            accounts=["HASHA"],
            transactions_payload=_tx_payload(),
        )
        result = get_transaction_history(client, "2026-09-01", "2026-09-30")
        assert result.outcome == "ok"
        assert result.total_count == 1
        assert result.movements[0].symbol == "AAPL"

    def test_account_hash_taken_from_hash_value_key(self) -> None:
        client = LiveLikeClient(
            accounts=["REALHASH123"],
            transactions_payload=_tx_payload(),
        )
        result = get_transaction_history(client, "2026-09-01", "2026-09-30")
        assert result.movements[0].account_hash == "REALHASH123"

    def test_provider_receives_ny_bounded_datetimes(self) -> None:
        """The API rejects bare ``YYYY-MM-DD``; the orchestration must send
        ISO-8601 datetimes bounded by the account's market timezone
        (America/New_York, both edges inclusive — spec clarifications)."""
        client = LiveLikeClient(
            accounts=["HASHA"], transactions_payload={"transactions": []}
        )
        get_transaction_history(client, "2026-09-01", "2026-09-30")
        kwargs = client.last_transactions_kwargs
        assert kwargs["startDate"] == "2026-09-01T00:00:00-04:00"
        assert kwargs["endDate"] == "2026-09-30T23:59:59-04:00"

    def test_top_level_list_payload_from_real_api(self) -> None:
        """The real provider returns a top-level JSON list of transactions,
        not a ``{"transactions": [...]}`` envelope (found live 2026-10-23)."""
        client = LiveLikeClient(
            accounts=["HASHA"],
            transactions_payload=_tx_payload()["transactions"],
        )
        result = get_transaction_history(client, "2026-09-01", "2026-09-30")
        assert result.outcome == "ok"
        assert result.total_count == 1
        assert result.movements[0].symbol == "AAPL"

    def test_http_401_maps_to_reauth_required(self) -> None:
        client = LiveLikeClient(accounts=["HASHA"], transactions_status=401)
        result = get_transaction_history(client, "2026-09-01", "2026-09-30")
        assert result.outcome == "reauth_required"
        assert result.detail == "reauth_needed"

    def test_http_500_maps_to_transient_failure(self) -> None:
        client = LiveLikeClient(accounts=["HASHA"], transactions_status=500)
        result = get_transaction_history(client, "2026-09-01", "2026-09-30")
        assert result.outcome == "transient_failure"
        assert result.retryable is True

    def test_partial_failure_when_one_account_returns_500(self) -> None:
        class MixedClient(LiveLikeClient):
            def transactions(self, accountHash, startDate, endDate, types, symbol=None):
                self.transactions_calls.append(accountHash)
                status = 500 if accountHash == "HASHB" else 200
                return _response(_tx_payload(), status=status)

        client = MixedClient(accounts=["HASHA", "HASHB"])
        result = get_transaction_history(client, "2026-09-01", "2026-09-30")
        assert result.outcome == "partial_failure"
        assert result.movements, "successful account's movements must not be dropped"
        assert result.accounts_failed is not None
        assert [f.account_hash for f in result.accounts_failed] == ["HASHB"]
        assert result.accounts_failed[0].detail == "transient"


# =============================================================================
# 1b. Real provider payload shape (found live 2026-10-23)
# =============================================================================


def _real_trade_tx() -> dict:
    """A TRADE as the real API sends it: ``time`` (no ``transactionDate``),
    no ``description``, no top-level ``instrument`` — the instrument rides
    inside ``transferItems`` with ``assetType``."""
    return {
        "activityId": "900",
        "type": "TRADE",
        "time": "2026-09-23T18:27:05+0000",
        "netAmount": -2318.9,
        "transferItems": [
            {"amount": 10.0, "instrument": {
                "symbol": "AAPL", "assetType": "EQUITY"}},
            {"amount": -2318.9, "instrument": None},
        ],
    }


class TestRealProviderShape:
    def test_occurred_at_from_time_field(self) -> None:
        client = LiveLikeClient(
            accounts=["HASHA"],
            transactions_payload=[_real_trade_tx()],
        )
        result = get_transaction_history(client, "2026-09-01", "2026-09-30")
        assert result.movements[0].occurred_at == "2026-09-23T18:27:05+0000"

    def test_instrument_extracted_from_transfer_items(self) -> None:
        client = LiveLikeClient(
            accounts=["HASHA"],
            transactions_payload=[_real_trade_tx()],
        )
        result = get_transaction_history(client, "2026-09-01", "2026-09-30")
        entry = result.movements[0]
        assert entry.symbol == "AAPL"
        assert entry.instrument_type == "EQUITY"

    def test_description_absent_is_empty_not_crash(self) -> None:
        client = LiveLikeClient(
            accounts=["HASHA"],
            transactions_payload=[_real_trade_tx()],
        )
        result = get_transaction_history(client, "2026-09-01", "2026-09-30")
        assert result.movements[0].description == ""


# =============================================================================
# 1c. Multi-leg trade shape (found live 2026-10-24, bug nok-symbol-filter-miss)
# =============================================================================


def _cash_leg(amount: float) -> dict:
    """A fee/cash transferItem as the real API sends it: the instrument is
    NOT ``None`` — it is ``CURRENCY_USD`` / ``CURRENCY``."""
    return {
        "amount": amount,
        "instrument": {
            "symbol": "CURRENCY_USD",
            "assetType": "CURRENCY",
            "description": "USD currency",
        },
    }


def _real_multileg_option_tx() -> dict:
    """A real option trade as the API sends it (found live 2026-10-24):
    four fee/cash legs come FIRST — each carrying a non-``None``
    ``instrument`` with ``symbol=CURRENCY_USD`` / ``assetType=CURRENCY`` —
    and the traded option leg comes LAST.  Curating the first transferItem
    with a symbol mislabels the whole trade as ``CURRENCY_USD`` and hides
    the instrument from the symbol filter."""
    return {
        "activityId": "902",
        "type": "TRADE",
        "time": "2026-06-05T18:59:46+0000",
        "netAmount": -11.56,
        "transferItems": [
            _cash_leg(5.2),
            _cash_leg(0.02),
            _cash_leg(0.1),
            _cash_leg(0.03),
            {
                "amount": -8,
                "instrument": {
                    "symbol": "NOK   260821P00013000",
                    "assetType": "OPTION",
                    "description": "NOKIA CORP 08/21/2026 $1.30 Put",
                    "putCall": "PUT",
                    "underlyingSymbol": "NOK",
                },
                "price": 1.44,
                "positionEffect": "OPENING",
            },
        ],
    }


class TestMultiLegTradeShape:
    def test_option_leg_curated_over_fee_legs(self) -> None:
        """The traded instrument must win over the CURRENCY_USD fee legs."""
        client = LiveLikeClient(
            accounts=["HASHA"],
            transactions_payload=[_real_multileg_option_tx()],
        )
        result = get_transaction_history(client, "2026-06-01", "2026-06-30")
        entry = result.movements[0]
        assert entry.symbol == "NOK   260821P00013000", (
            f"Expected the option OCC symbol, got '{entry.symbol}' — the "
            "fee/cash legs must not mask the traded instrument"
        )
        assert entry.instrument_type == "OPTION"
        assert entry.underlying_symbol == "NOK"

    def test_symbol_filter_matches_multileg_option(self) -> None:
        """``symbol="NOK"`` must match the trade whose OCC root is NOK (M2)
        instead of reporting ``no_movements_for_instrument``."""
        client = LiveLikeClient(
            accounts=["HASHA"],
            transactions_payload=[_real_multileg_option_tx()],
            instruments_payload=[{"symbol": "NOK", "instrumentType": "EQUITY"}],
        )
        result = get_transaction_history(
            client, "2026-06-01", "2026-06-30", symbol="NOK"
        )
        assert result.outcome == "ok"
        assert result.total_count == 1
        assert result.movements[0].symbol == "NOK   260821P00013000"

    def test_cash_only_trade_stays_currency(self) -> None:
        """A movement with only CURRENCY_USD legs keeps ``CURRENCY_USD``
        as its curated symbol (no regression for genuine cash movements)."""
        tx = {
            "activityId": "903",
            "type": "CASH_RECEIPT",
            "time": "2026-06-05T18:59:46+0000",
            "netAmount": 100.0,
            "transferItems": [_cash_leg(100.0)],
        }
        client = LiveLikeClient(
            accounts=["HASHA"],
            transactions_payload=[tx],
        )
        result = get_transaction_history(client, "2026-06-01", "2026-06-30")
        entry = result.movements[0]
        assert entry.symbol == "CURRENCY_USD"
        assert entry.instrument_type == "CURRENCY"

    def test_first_noncurrency_leg_wins_deterministically(self) -> None:
        """With several non-currency legs, the first one in encounter order
        is curated — the rule must be deterministic."""
        tx = {
            "activityId": "904",
            "type": "TRADE",
            "time": "2026-06-05T18:59:46+0000",
            "netAmount": 0.0,
            "transferItems": [
                {"amount": 1, "instrument": {
                    "symbol": "AAPL", "assetType": "EQUITY"}},
                {"amount": -1, "instrument": {
                    "symbol": "MSFT", "assetType": "EQUITY"}},
            ],
        }
        client = LiveLikeClient(
            accounts=["HASHA"],
            transactions_payload=[tx],
        )
        result = get_transaction_history(client, "2026-06-01", "2026-06-30")
        assert result.movements[0].symbol == "AAPL"

    def test_top_level_currency_instrument_not_preferred_over_legs(self) -> None:
        """A top-level ``CURRENCY`` instrument must not mask the traded
        instrument carried inside ``transferItems``."""
        tx = dict(_real_multileg_option_tx())
        tx["instrument"] = {
            "symbol": "CURRENCY_USD", "instrumentType": "CURRENCY",
        }
        client = LiveLikeClient(
            accounts=["HASHA"],
            transactions_payload=[tx],
        )
        result = get_transaction_history(client, "2026-06-01", "2026-06-30")
        assert result.movements[0].symbol == "NOK   260821P00013000"


# =============================================================================
# 2. instruments() Response unwrapping (unknown symbol detection)
# =============================================================================


class TestInstrumentsResponseUnwrapping:
    def test_empty_instruments_response_raises_instrument_not_found(self) -> None:
        client = LiveLikeClient(
            accounts=["HASHA"],
            transactions_payload=_tx_payload(),
            instruments_payload=[],
        )
        with pytest.raises(InstrumentNotFoundError, match="ZZZZZZ"):
            get_transaction_history(
                client, "2026-09-01", "2026-09-30", symbol="ZZZZZZ"
            )

    def test_known_symbol_passes_validation_and_filters_upstream(self) -> None:
        client = LiveLikeClient(
            accounts=["HASHA"],
            transactions_payload=_tx_payload(),
            instruments_payload=[{"symbol": "AAPL", "instrumentType": "EQUITY"}],
        )
        result = get_transaction_history(
            client, "2026-09-01", "2026-09-30", symbol="AAPL"
        )
        assert result.outcome == "ok"
        assert result.movements[0].symbol == "AAPL"
        # The SDK only accepts lowercase projections (research D6 fix —
        # 'SYMBOL_SEARCH' is rejected by the SDK validator, found live).
        assert client.last_instruments_kwargs["projection"] == "symbol-search"


# =============================================================================
# 3. ToolError conversion — actionable messages reach the MCP client
# =============================================================================


class TestToolErrorConversion:
    def test_validation_error_becomes_tool_error_naming_dates(self) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        with pytest.raises(ToolError, match=r"2026-09-01.*2026-09-30"):
            get_transaction_history_tool(None, "2026-09-30", "2026-09-01")

    def test_malformed_date_becomes_tool_error_naming_format(self) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        with pytest.raises(ToolError, match=r"YYYY-MM-DD"):
            get_transaction_history_tool(None, "01-09-2026", "2026-09-30")

    def test_unknown_symbol_becomes_tool_error_naming_symbol(self) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        client = LiveLikeClient(
            accounts=["HASHA"],
            transactions_payload=_tx_payload(),
            instruments_payload=[],
        )
        with pytest.raises(ToolError, match="ZZZZZZ"):
            get_transaction_history_tool(
                client, "2026-09-01", "2026-09-30", symbol="ZZZZZZ"
            )
