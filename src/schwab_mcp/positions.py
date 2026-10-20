"""Pydantic models and orchestration for open positions data.

Defines ``PositionEntry`` and ``PositionsResult`` with validation rules
from data-model.md §1–§2, plus ``get_open_positions()`` — the first real
MCP tool of the server.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field, model_validator

from schwab_mcp.errors import (
    ConnectivityError,
    ReauthorizationRequiredError,
    TokenStoreCorruptedError,
)
from schwab_mcp.log import auth_event


class InstrumentType(str, Enum):
    """Allowed instrument types from the provider's ``assetType`` field."""

    EQUITY = "EQUITY"
    OPTION = "OPTION"
    MUTUAL_FUND = "MUTUAL_FUND"
    FIXED_INCOME = "FIXED_INCOME"
    CASH_EQUIVALENT = "CASH_EQUIVALENT"


class OutcomeType(str, Enum):
    """Allowed outcome classifications for a positions query."""

    OK = "ok"
    PARTIAL_FAILURE = "partial_failure"
    TRANSIENT_FAILURE = "transient_failure"
    REAUTH_REQUIRED = "reauth_required"


class PutCall(str, Enum):
    """Call or put indicator for option instruments."""

    PUT = "PUT"
    CALL = "CALL"


class DetailType(str, Enum):
    """Closed vocabulary for result detail field."""

    DATA_RECEIVED = "data_received"
    NO_POSITIONS = "no_positions"
    ACCOUNT_FAILED = "account_failed"
    PROVIDER_UNREACHABLE = "provider_unreachable"
    REAUTH_NEEDED = "reauth_needed"
    STORE_ABSENT = "store_absent"
    STORE_CORRUPTED = "store_corrupted"


class AccountFailureDetail(str, Enum):
    """Allowed detail values for accounts_failed entries."""

    PROVIDER_ERROR = "provider_error"
    TRANSIENT = "transient"


class PositionEntry(BaseModel):
    """A single position entry (data-model.md §1).

    Represents one (account_hash, symbol) pair with the curated set of
    metadata fields.  Option-specific fields are present only for
    ``instrument_type == "OPTION"``.
    """

    account_hash: str = Field(..., min_length=1, description="Opaque account identifier; never the raw account number")
    symbol: str = Field(..., min_length=1, description="Instrument symbol")
    instrument_type: InstrumentType = Field(..., description="Asset type classification")
    description: str = Field(..., min_length=1, description="Human-readable instrument description")
    quantity: float = Field(..., description="Signed quantity (long - short); positive for long, negative for short")
    average_price: float = Field(..., ge=0, description="Average acquisition cost")
    market_value: float = Field(..., description="Current market value")
    unrealized_pl: float = Field(..., description="Unrealized profit/loss (negative = loss)")
    price_timestamp: str = Field(..., description="ISO-8601 UTC timestamp of price retrieval")

    # Option-specific fields — only present when instrument_type == "OPTION"
    underlying_symbol: Optional[str] = Field(None, description="Underlying instrument symbol (options only)")
    put_call: Optional[PutCall] = Field(None, description="Put or call indicator (options only)")
    strike_price: Optional[float] = Field(None, gt=0, description="Strike price (options only)")
    expiration_date: Optional[str] = Field(None, description="Expiration date (options only)")

    # Extended fields — only present when extended=true
    extended: Optional[dict] = Field(None, description="Extended provider passthrough fields")

    @model_validator(mode="after")
    def _validate_quantity_nonzero(self) -> "PositionEntry":
        """Quantity must never be zero (FR-015)."""
        if self.quantity == 0:
            raise ValueError("quantity must be non-zero; positions with zero quantity are omitted (FR-015)")
        return self

    @model_validator(mode="after")
    def _validate_option_fields(self) -> "PositionEntry":
        """Option fields present ⇔ instrument_type == OPTION; absent for other types."""
        is_option = self.instrument_type == InstrumentType.OPTION
        option_fields = [self.underlying_symbol, self.put_call, self.strike_price, self.expiration_date]
        has_option_values = any(f is not None for f in option_fields)

        if is_option and not has_option_values:
            raise ValueError(
                "Option-specific fields (underlying_symbol, put_call, strike_price, "
                "expiration_date) are required when instrument_type == 'OPTION'"
            )
        if not is_option and has_option_values:
            raise ValueError(
                "Option-specific fields must not be present when instrument_type != 'OPTION'"
            )
        return self


class AccountFailed(BaseModel):
    """Describes a single account that failed during a multi-account query."""

    account_hash: str = Field(..., min_length=1, description="Opaque identifier of the failed account")
    detail: AccountFailureDetail = Field(..., description="Reason for the failure")


class PositionsResult(BaseModel):
    """The single structured result of a ``get_open_positions`` invocation (data-model.md §2).

    Auto-classifying result that covers all possible outcomes.
    """

    outcome: OutcomeType = Field(..., description="Result classification")
    positions: list[PositionEntry] = Field(default_factory=list, description="List of position entries")
    accounts_failed: Optional[list[AccountFailed]] = Field(None, description="Accounts that failed (partial_failure only)")
    retryable: bool = Field(..., description="Whether the agent should retry")
    detail: DetailType = Field(..., description="Specific detail within the outcome class")
    retrieved_at: str = Field(..., description="ISO-8601 UTC timestamp of payload retrieval")

    @model_validator(mode="after")
    def _validate_outcome_rules(self) -> "PositionsResult":
        """Cross-field validation for outcome-specific rules."""
        is_transient = self.outcome == OutcomeType.TRANSIENT_FAILURE
        is_ok = self.outcome == OutcomeType.OK
        is_partial = self.outcome == OutcomeType.PARTIAL_FAILURE
        is_reauth = self.outcome == OutcomeType.REAUTH_REQUIRED

        if self.retryable and not is_transient:
            raise ValueError("retryable=True is only allowed when outcome == 'transient_failure'")
        if is_transient and not self.retryable:
            raise ValueError("transient_failure outcome requires retryable=True")

        if self.positions and (is_transient or is_reauth):
            raise ValueError("positions must be empty for transient_failure and reauth_required outcomes")
        if not self.positions and is_ok and self.detail not in (DetailType.NO_POSITIONS, DetailType.DATA_RECEIVED):
            raise ValueError("ok outcome with empty positions must use detail='no_positions'")

        if self.accounts_failed is not None and not is_partial:
            raise ValueError("accounts_failed is only allowed when outcome == 'partial_failure'")
        if is_partial and self.accounts_failed is None:
            raise ValueError("partial_failure outcome requires accounts_failed")

        return self


# =============================================================================
# Helper utilities
# =============================================================================


def _hash_account(account_number: str) -> str:
    """Produce an opaque hash from a raw Schwab account number."""
    return hashlib.sha256(account_number.encode()).hexdigest()[:8]


def _compute_unrealized_pl(
    market_value: float,
    average_price: float,
    quantity: float,
) -> float:
    """Compute unrealized P/L per research D3.

    Formula: ``marketValue - (averagePrice × |quantity|) × sign(quantity)``
    which simplifies to ``market_value - average_price * quantity``.
    """
    return market_value - average_price * quantity


def utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string parseable by Python.

    Produces ``2026-10-20T20:27:51+00:00`` (standard ISO-8601, no non-standard
    ``Z+00:00`` suffix).  Parseable via ``datetime.fromisoformat()``.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# =============================================================================
# Internal mapping (provider-agnostic payload → PositionsResult)
# =============================================================================

# Fields from the provider payload that should be passed through as extended
# data when ``extended=True`` (defined per research D3).
_EXTENDED_FIELDS = frozenset({
    "cusip",
    "settledLongQuantity",
    "settledShortQuantity",
    "dayQuanity",  # sic — provider field name
    "currentDayProfitLoss",
    "maintenanceRequirement",
})


def _collect_extended(pos: dict) -> dict:
    """Gather extended provider fields from a position dict into a passthrough dict."""
    result = {}
    for field in _EXTENDED_FIELDS:
        if field in pos:
            result[field] = pos[field]
    return result


def map_provider_positions(payload: dict, extended: bool = False) -> PositionsResult:
    """Map an already-processed provider payload to a ``PositionsResult``.

    This function is the pure mapping core, tested by T004. The payload
    is expected to have ``accounts`` (list of account dicts with
    ``accountHash`` and ``positions``) and ``retrieved_at`` (ISO-8601).

    Each position has flat fields: ``symbol``, ``assetType``,
    ``description``, ``longQuantity``, ``shortQuantity``,
    ``averagePrice``, ``marketValue``, ``unrealizedPL``
    and optional option-specific fields (``underlyingSymbol``,
    ``putCall``, ``strikePrice``, ``expirationDate``)
    and extended passthrough fields (``cusip``, etc.).
    """
    accounts_raw: list[dict] = payload.get("accounts", [])
    retrieved_at: str = payload.get("retrieved_at", utc_now_iso())

    consolidated: dict[tuple[str, str], dict] = {}
    total_positions = 0

    for account in accounts_raw:
        account_hash = account.get("accountHash", "")
        positions_raw: list[dict] = account.get("positions", [])

        for pos in positions_raw:
            symbol = pos.get("symbol", "")
            long_qty = pos.get("longQuantity", 0.0)
            short_qty = pos.get("shortQuantity", 0.0)
            quantity = long_qty - short_qty

            if quantity == 0:
                continue  # FR-015: omit zero-quantity positions

            average_price = pos.get("averagePrice", 0.0)
            market_value = pos.get("marketValue", 0.0)
            instrument_type_str = pos.get("assetType", "EQUITY")
            description = pos.get("description", "")

            # Collect option-specific fields
            underlying_symbol = pos.get("underlyingSymbol", None)
            put_call_str = pos.get("putCall", None)
            strike_price = pos.get("strikePrice", None)
            expiration_date = pos.get("expirationDate", None)

            # Collect extended passthrough fields
            extended_dict: dict = {}
            if extended:
                extended_dict = _collect_extended(pos)

            key = (account_hash, symbol)
            if key in consolidated:
                existing = consolidated[key]
                existing["quantity"] += quantity
                existing["market_value"] += market_value
                existing["average_price_sum"] += average_price
                existing["count"] += 1
                existing["average_price"] = existing["average_price_sum"] / existing["count"]
                # If extended data exists, keep the first occurrence's extended data
                if extended and not existing.get("extended"):
                    existing["extended"] = extended_dict
            else:
                consolidated[key] = {
                    "account_hash": account_hash,
                    "symbol": symbol,
                    "instrument_type": instrument_type_str,
                    "description": description,
                    "quantity": quantity,
                    "average_price": average_price,
                    "average_price_sum": average_price,
                    "count": 1,
                    "market_value": market_value,
                    "unrealized_pl": _compute_unrealized_pl(market_value, average_price, quantity),
                    "price_timestamp": retrieved_at,
                    "underlying_symbol": underlying_symbol,
                    "put_call": put_call_str,
                    "strike_price": strike_price,
                    "expiration_date": expiration_date,
                    "extended": extended_dict if extended else None,
                }

            total_positions += 1

    if total_positions == 0:
        return PositionsResult(
            outcome="ok",
            positions=[],
            detail="no_positions",
            retryable=False,
            retrieved_at=retrieved_at,
        )

    entries: list[PositionEntry] = []
    for data in consolidated.values():
        kw: dict = {
            "account_hash": data["account_hash"],
            "symbol": data["symbol"],
            "instrument_type": data["instrument_type"],
            "description": data["description"],
            "quantity": data["quantity"],
            "average_price": data["average_price"],
            "market_value": data["market_value"],
            "unrealized_pl": _compute_unrealized_pl(
                data["market_value"], data["average_price"], data["quantity"],
            ),
            "price_timestamp": data["price_timestamp"],
        }

        # Add option fields if present
        if data.get("underlying_symbol"):
            kw["underlying_symbol"] = data["underlying_symbol"]
            kw["put_call"] = data.get("put_call")
            kw["strike_price"] = data.get("strike_price")
            kw["expiration_date"] = data.get("expiration_date")

        # Add extended passthrough if present
        if data.get("extended"):
            kw["extended"] = data["extended"]

        entries.append(PositionEntry(**kw))

    return PositionsResult(
        outcome="ok",
        positions=entries,
        detail="data_received",
        retryable=False,
        retrieved_at=retrieved_at,
    )


# =============================================================================
# MCP Tool: get_open_positions
# =============================================================================


def get_open_positions(
    client: Any,
    extended: bool = False,
) -> PositionsResult:
    """Fetch all open positions across all linked accounts.

    Parameters
    ----------
    client:
        A schwabdev Client instance (or fake) with an
        ``account_details_all(fields)`` method.
    extended:
        If ``True``, include extended provider passthrough fields
        on each position entry (FR-003a).

    Returns
    -------
    PositionsResult
        A structured result with outcome, positions, and metadata.
    """
    retrieved_at = utc_now_iso()
    mode = "extended" if extended else "curated"

    # Emit start audit event (FR-014)
    auth_event("positions_query_start", "initiated", detail=mode)

    try:
        payload = client.account_details_all(fields="positions")
    except ConnectivityError:
        auth_event(
            "positions_query_failure",
            "transient",
            detail="provider_unreachable",
        )
        return PositionsResult(
            outcome="transient_failure",
            positions=[],
            detail="provider_unreachable",
            retryable=True,
            retrieved_at=retrieved_at,
        )
    except ReauthorizationRequiredError:
        auth_event(
            "positions_query_failure",
            "reauth",
            detail="reauth_needed",
        )
        return PositionsResult(
            outcome="reauth_required",
            positions=[],
            detail="reauth_needed",
            retryable=False,
            retrieved_at=retrieved_at,
        )
    except TokenStoreCorruptedError:
        auth_event(
            "positions_query_failure",
            "reauth",
            detail="store_corrupted",
        )
        return PositionsResult(
            outcome="reauth_required",
            positions=[],
            detail="store_corrupted",
            retryable=False,
            retrieved_at=retrieved_at,
        )

    # Check for per-account failures (FR-010 / D7)
    accounts_failed_list = _detect_account_failures(payload, retrieved_at)
    if accounts_failed_list:
        # Some or all accounts failed — isolate per-account
        successful_accounts = _extract_successful_accounts(payload)
        if successful_accounts:
            # Partial failure: some worked, some didn't
            internal_payload = _transform_provider_payload(
                {"accountDetails": successful_accounts},
                retrieved_at,
                extended=extended,
            )
            pos_result = map_provider_positions(internal_payload, extended=extended)
            pos_result.outcome = "partial_failure"
            pos_result.detail = "account_failed"
            pos_result.accounts_failed = accounts_failed_list
            pos_result.retryable = False
        else:
            # All accounts failed
            pos_result = PositionsResult(
                outcome="partial_failure",
                positions=[],
                detail="account_failed",
                retryable=False,
                retrieved_at=retrieved_at,
                accounts_failed=accounts_failed_list,
            )
    else:
        # All accounts succeeded — normal mapping path
        internal_payload = _transform_provider_payload(payload, retrieved_at, extended=extended)
        pos_result = map_provider_positions(internal_payload, extended=extended)

    # Override timestamps
    pos_result.retrieved_at = retrieved_at
    for entry in pos_result.positions:
        entry.price_timestamp = retrieved_at

    # Emit terminal audit event
    if pos_result.outcome == "ok":
        result_detail = "positions_found" if pos_result.positions else "no_positions"
        auth_event("positions_query_success", "ok", detail=result_detail)
    elif pos_result.outcome == "partial_failure":
        auth_event("positions_query_success", "partial_failure", detail="account_failed")
    elif pos_result.outcome == "transient_failure":
        auth_event("positions_query_failure", "transient", detail="provider_unreachable")
    elif pos_result.outcome == "reauth_required":
        pass  # Already emitted in the error handler above

    return pos_result


def _detect_account_failures(provider_payload: dict, retrieved_at: str) -> list[dict]:
    """Detect per-account failures in the provider payload (FR-010).

    Checks each entry in ``accountDetails`` for an ``error`` key. If found,
    the account is considered failed and added to the returned list.
    If no account has an error, returns an empty list.

    Returns a list of ``{"account_hash": str, "detail": str}`` dicts for
    the failed accounts, or an empty list if all accounts succeeded.
    """
    account_details = provider_payload.get("accountDetails", [])
    failed: list[dict] = []

    for account in account_details:
        if "error" in account:
            account_number = account.get("accountNumber", "")
            account_hash = _hash_account(account_number)
            # Classify the error detail
            err = account["error"]
            error_detail = "transient" if isinstance(err, dict) and err.get("transient") else "provider_error"
            failed.append({
                "account_hash": account_hash,
                "detail": error_detail,
            })

    return failed


def _extract_successful_accounts(provider_payload: dict) -> list[dict]:
    """Extract account entries that do NOT have an ``error`` key."""
    account_details = provider_payload.get("accountDetails", [])
    return [a for a in account_details if "error" not in a]


def _transform_provider_payload(
    provider_payload: dict,
    retrieved_at: str,
    extended: bool = False,
) -> dict:
    """Transform a provider payload (from ``account_details_all``) into the
    internal format expected by ``map_provider_positions``.

    The provider returns:
    ``{"accountDetails": [{"accountNumber": "...", "positions": [{"instrument": {...}, ...}]}]}``

    The internal format is:
    ``{"accounts": [{"accountHash": "<opaque>", "positions": [...]}], "retrieved_at": "..."}``

    Parameters
    ----------
    extended:
        If ``True``, passthrough extra provider fields (cusip, etc.)
        into each position dict.
    """
    account_details = provider_payload.get("accountDetails", [])
    accounts_out: list[dict] = []

    for account in account_details:
        account_number = account.get("accountNumber", "")
        account_hash = _hash_account(account_number)
        positions_raw: list[dict] = account.get("positions", [])
        positions_out: list[dict] = []

        for pos in positions_raw:
            instrument = pos.get("instrument", {})
            entry: dict = {
                "symbol": instrument.get("symbol", ""),
                "assetType": instrument.get("assetType", "EQUITY"),
                "description": instrument.get("description", ""),
                "longQuantity": pos.get("longQuantity", 0.0),
                "shortQuantity": pos.get("shortQuantity", 0.0),
                "averagePrice": pos.get("averagePrice", 0.0),
                "marketValue": pos.get("marketValue", 0.0),
                "unrealizedPL": _compute_unrealized_pl(
                    pos.get("marketValue", 0.0),
                    pos.get("averagePrice", 0.0),
                    pos.get("longQuantity", 0.0) - pos.get("shortQuantity", 0.0),
                ),
            }

            # Map option-specific fields from instrument sub-object
            asset_type = instrument.get("assetType", "")
            if asset_type == "OPTION":
                entry["underlyingSymbol"] = instrument.get("underlyingSymbol", "")
                entry["putCall"] = instrument.get("putCall", "CALL")
                entry["strikePrice"] = instrument.get("strikePrice", 0.0)
                entry["expirationDate"] = instrument.get("expirationDate", "")

            # Passthrough extended fields at the position level
            if extended:
                for f in _EXTENDED_FIELDS:
                    if f in pos:
                        entry[f] = pos[f]
                # Note: 'instrument' sub-object is NOT included here because
                # its key fields (symbol, assetType, description) are already
                # extracted into the curated fields — duplicating them in
                # extended saves no information and wastes token budget.

            positions_out.append(entry)

        accounts_out.append({
            "accountHash": account_hash,
            "positions": positions_out,
        })

    return {
        "accounts": accounts_out,
        "retrieved_at": retrieved_at,
    }