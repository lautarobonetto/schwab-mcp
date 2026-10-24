"""Regression tests: live-SDK response handling for ``get_open_positions``.

Manual testing against the real ``schwabdev`` client (found 2026-10-23,
bug ``positions-response-unwrap``) revealed that feature 003 was built
against an assumed payload shape that the provider does not return:

1. ``Client.account_details_all()`` returns a ``requests.Response`` — the
   orchestration must unwrap the JSON body (same defect fixed for 006 in
   ``transactions.py``).
2. The real payload is a **top-level list** of
   ``{"aggregatedBalance", "securitiesAccount"}`` — not the assumed
   ``{"accountDetails": [...]}`` dict.
3. The real account identifier is the provider's opaque ``hashValue``
   from ``linked_accounts()``, matched by ``accountNumber`` — not a
   locally computed hash of the raw account number.

References: .specify/bugs/positions-response-unwrap/assessment.md,
spec 003 FR-008/FR-010, credential-safety constraints of the constitution.
"""

from __future__ import annotations

import json

import pytest
from tests.unit.helpers import build_response

from schwab_mcp.positions import get_open_positions

RAW_ACCOUNT_NUMBER = "12345678"
PROVIDER_HASH = "REALHASHABC123"


def _real_positions_payload() -> list:
    """The real bulk payload shape: list of {aggregatedBalance, securitiesAccount}."""
    return [
        {
            "aggregatedBalance": {"liquidationValue": 5910.0},
            "securitiesAccount": {
                "accountNumber": RAW_ACCOUNT_NUMBER,
                "positions": [
                    {
                        "instrument": {
                            "symbol": "SPY",
                            "assetType": "EQUITY",
                            "description": "SPDR S&P 500 ETF Trust",
                        },
                        "longQuantity": 10.0,
                        "shortQuantity": 0.0,
                        "averagePrice": 580.25,
                        "marketValue": 5910.0,
                    }
                ],
            },
        }
    ]


class LiveLikePositionsClient:
    """Fake client returning ``requests.Response`` objects, like the SDK."""

    def __init__(
        self,
        accounts_listing=None,
        positions_raw=None,
        positions_status: int = 200,
        accounts_status: int = 200,
    ) -> None:
        self.accounts_listing = (
            accounts_listing
            if accounts_listing is not None
            else [{"hashValue": PROVIDER_HASH, "accountNumber": RAW_ACCOUNT_NUMBER}]
        )
        self.positions_raw = (
            positions_raw if positions_raw is not None else _real_positions_payload()
        )
        self.positions_status = positions_status
        self.accounts_status = accounts_status

    def linked_accounts(self):
        return build_response(self.accounts_listing, status=self.accounts_status)

    def account_details_all(self, fields: str = "positions"):
        return build_response(self.positions_raw, status=self.positions_status)


class TestLiveSdkResponses:
    def test_ok_from_real_shape_responses(self) -> None:
        result = get_open_positions(LiveLikePositionsClient())
        assert result.outcome == "ok"
        assert result.positions, "positions must be mapped from the real payload"
        entry = result.positions[0]
        assert entry.symbol == "SPY"
        assert entry.quantity == 10.0
        assert entry.average_price == 580.25

    def test_account_hash_is_provider_hash_value(self) -> None:
        """The account identifier must be the provider's ``hashValue``
        (cross-referenced by ``accountNumber``), not a locally computed
        hash and never the raw account number."""
        result = get_open_positions(LiveLikePositionsClient())
        assert result.positions[0].account_hash == PROVIDER_HASH
        assert result.positions[0].account_hash != RAW_ACCOUNT_NUMBER

    def test_http_401_maps_to_reauth_required(self) -> None:
        client = LiveLikePositionsClient(positions_status=401)
        result = get_open_positions(client)
        assert result.outcome == "reauth_required"
        assert result.detail == "reauth_needed"

    def test_http_500_maps_to_transient_failure(self) -> None:
        client = LiveLikePositionsClient(positions_status=500)
        result = get_open_positions(client)
        assert result.outcome == "transient_failure"
        assert result.retryable is True

    def test_unmatched_account_number_is_partial_failure(self) -> None:
        """An account whose ``accountNumber`` has no ``hashValue`` in
        ``linked_accounts()`` must surface as an explicit per-account
        failure — never silently dropped, never locally hashed."""
        client = LiveLikePositionsClient(
            positions_raw=_real_positions_payload(),
            accounts_listing=[{"hashValue": "OTHER", "accountNumber": "87654321"}],
        )
        result = get_open_positions(client)
        assert result.outcome == "partial_failure"
        assert result.accounts_failed, "unmatched account must be reported"
        assert all(
            f.account_hash != RAW_ACCOUNT_NUMBER for f in result.accounts_failed
        )

    def test_option_strike_and_expiry_parsed_from_occ_symbol(self) -> None:
        """Real OPTION instruments carry ``putCall`` and ``underlyingSymbol``
        but NOT ``strikePrice``/``expirationDate`` — those are encoded in
        the OCC symbol (found live 2026-10-24)."""
        client = LiveLikePositionsClient(
            positions_raw=[
                {
                    "aggregatedBalance": {},
                    "securitiesAccount": {
                        "accountNumber": RAW_ACCOUNT_NUMBER,
                        "positions": [
                            {
                                "instrument": {
                                    "symbol": "AMD  261120P00090000",
                                    "assetType": "OPTION",
                                    "description": "AMD Nov 20 2026 90 Put",
                                    "putCall": "PUT",
                                    "underlyingSymbol": "AMD",
                                },
                                "longQuantity": 1.0,
                                "shortQuantity": 0.0,
                                "averagePrice": 250.0,
                                "marketValue": 2500.0,
                            }
                        ],
                    },
                }
            ],
        )
        result = get_open_positions(client)
        assert result.outcome == "ok"
        entry = result.positions[0]
        assert entry.instrument_type == "OPTION"
        assert entry.strike_price == 90.0
        assert entry.expiration_date == "2026-11-20"
        assert entry.put_call == "PUT"
        assert entry.underlying_symbol == "AMD"

    def test_raw_account_number_never_in_output(self) -> None:
        result = get_open_positions(LiveLikePositionsClient())
        serialized = result.model_dump_json()
        assert RAW_ACCOUNT_NUMBER not in serialized
