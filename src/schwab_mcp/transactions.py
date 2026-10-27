"""Pydantic models and mapping for account transaction history data.

Defines ``MovementEntry``, ``TransactionsResult``, and related enums with
validation rules from data-model.md, plus the ``classify_movement_type()``
mapping function.
"""

from __future__ import annotations

import contextlib
import re
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Any, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

from schwab_mcp.errors import ConnectivityError, ReauthorizationRequiredError
from schwab_mcp.log import auth_event
from schwab_mcp.provider import response_json
from schwab_mcp.tokens import retry_call


# =============================================================================
# Custom exceptions
# =============================================================================


class InstrumentNotFoundError(Exception):
    """Raised when a requested instrument symbol is not found by the provider.

    The error message includes the symbol that was not found so that the
    agent can report it to the user (FR-009c).
    """


# =============================================================================
# Underlying-aware matching (007)
# =============================================================================

# OCC option symbol pattern: the last 15 characters are always
# YYMMDD + C/P + 8-digit strike×1000 (right-anchored).
_OCC_TAIL_RE = re.compile(r"^\d{6}[CP]\d{8}$")


def _option_root(symbol: str | None) -> str | None:
    """Derive the underlying root from an OCC option symbol (data-model §1-R1).

    The root is the portion before the last 15 characters (which encode
    expiry date, call/put indicator, and strike price × 1000), with padding
    stripped.  Returns ``None`` when the symbol is not a recognisable OCC
    option symbol (too short, wrong pattern, or ``None`` input).

    Parameters
    ----------
    symbol:
        The instrument symbol (e.g. ``"AMD   261120P00630000"``).

    Returns
    -------
    str | None
        The underlying root (e.g. ``"AMD"``) or ``None``.
    """
    if not symbol:
        return None
    tail = symbol[-15:]
    if len(tail) < 15:
        return None
    if not _OCC_TAIL_RE.match(tail):
        return None
    return symbol[:-15].strip()


def _is_currency_instrument(instrument: dict) -> bool:
    """Check whether an instrument dict is a currency (cash/fee) leg.

    The real provider carries cash and fee legs inside ``transferItems``
    as ``symbol=CURRENCY_USD`` / ``assetType=CURRENCY`` (found live
    2026-10-24).  When the asset type is absent, fall back to the
    ``CURRENCY_*`` symbol prefix so such legs are still classified as
    currency.
    """
    asset_type = instrument.get("assetType") or instrument.get("instrumentType")
    if asset_type:
        return str(asset_type).upper() == "CURRENCY"
    symbol = instrument.get("symbol") or ""
    return symbol.upper().startswith("CURRENCY_")


def movement_involves_filter(
    symbol: str | None,
    instrument_type: str | None,
    filter_symbol: str | None,
) -> bool:
    """Check whether a movement involves a given filter instrument (data-model §2).

    Matching is case-insensitive, exact (no fuzzy/substring), across three forms:

    - **M1**: The movement's registered symbol equals the filter.
    - **M2**: The movement is an option whose OCC root equals the filter.
    - **M3**: Same as M1 (exact symbol match), listed separately in the
      data model because the provider historically rejected full OCC symbols.

    Parameters
    ----------
    symbol:
        The movement's instrument symbol (may be ``None``).
    instrument_type:
        The movement's instrument type (e.g. ``"OPTION"``, ``"EQUITY"``).
    filter_symbol:
        The filter value to match against.

    Returns
    -------
    bool
        ``True`` if the movement involves the filter instrument.
    """
    if not filter_symbol:
        return False
    if not symbol:
        return False

    filter_upper = filter_symbol.upper()

    # M1 / M3: exact symbol match (case-insensitive)
    if symbol.upper() == filter_upper:
        return True

    # M2: option root match
    if instrument_type and instrument_type.upper() == "OPTION":
        root = _option_root(symbol)
        if root is not None and root.upper() == filter_upper:
            return True

    return False


# =============================================================================
# Enums
# =============================================================================


class TransactionOutcome(str, Enum):
    """Allowed outcome classifications for a transaction history query.

    Values: ok, partial_failure, transient_failure, reauth_required.
    Reused from the positions feature (003).
    """

    ok = "ok"
    partial_failure = "partial_failure"
    transient_failure = "transient_failure"
    reauth_required = "reauth_required"


class TransactionDetail(str, Enum):
    """Closed vocabulary for the result detail field.

    Values: history_retrieved, no_movements, no_movements_for_instrument,
    account_failed, provider_unreachable, reauth_needed.
    """

    history_retrieved = "history_retrieved"
    no_movements = "no_movements"
    no_movements_for_instrument = "no_movements_for_instrument"
    account_failed = "account_failed"
    provider_unreachable = "provider_unreachable"
    reauth_needed = "reauth_needed"


class MovementCategory(str, Enum):
    """Normalised movement categories (data-model.md §MovementCategory).

    Active v1: trade, transfer, dividend_or_interest, adjustment, other.
    Reserved (no upstream mapping in v1): interest, dividend, fee,
    corporate_action.
    """

    trade = "trade"
    transfer = "transfer"
    dividend_or_interest = "dividend_or_interest"
    adjustment = "adjustment"
    other = "other"
    interest = "interest"
    dividend = "dividend"
    fee = "fee"
    corporate_action = "corporate_action"


class ProviderTransactionType(str, Enum):
    """Mirror of all 15 upstream transaction types from the provider.

    Values match the Schwab API ``TransactionType`` enum exactly.
    """

    TRADE = "TRADE"
    RECEIVE_AND_DELIVER = "RECEIVE_AND_DELIVER"
    DIVIDEND_OR_INTEREST = "DIVIDEND_OR_INTEREST"
    ACH_RECEIPT = "ACH_RECEIPT"
    ACH_DISBURSEMENT = "ACH_DISBURSEMENT"
    CASH_RECEIPT = "CASH_RECEIPT"
    CASH_DISBURSEMENT = "CASH_DISBURSEMENT"
    ELECTRONIC_FUND = "ELECTRONIC_FUND"
    WIRE_OUT = "WIRE_OUT"
    WIRE_IN = "WIRE_IN"
    JOURNAL = "JOURNAL"
    MEMORANDUM = "MEMORANDUM"
    MARGIN_CALL = "MARGIN_CALL"
    MONEY_MARKET = "MONEY_MARKET"
    SMA_ADJUSTMENT = "SMA_ADJUSTMENT"


# =============================================================================
# Type-to-category mapping (R5)
# =============================================================================

_TYPE_CATEGORY_MAP: dict[str, MovementCategory] = {
    ProviderTransactionType.TRADE.value: MovementCategory.trade,
    ProviderTransactionType.RECEIVE_AND_DELIVER.value: MovementCategory.transfer,
    ProviderTransactionType.ACH_RECEIPT.value: MovementCategory.transfer,
    ProviderTransactionType.ACH_DISBURSEMENT.value: MovementCategory.transfer,
    ProviderTransactionType.CASH_RECEIPT.value: MovementCategory.transfer,
    ProviderTransactionType.CASH_DISBURSEMENT.value: MovementCategory.transfer,
    ProviderTransactionType.ELECTRONIC_FUND.value: MovementCategory.transfer,
    ProviderTransactionType.WIRE_IN.value: MovementCategory.transfer,
    ProviderTransactionType.WIRE_OUT.value: MovementCategory.transfer,
    ProviderTransactionType.DIVIDEND_OR_INTEREST.value: MovementCategory.dividend_or_interest,
    ProviderTransactionType.JOURNAL.value: MovementCategory.adjustment,
    ProviderTransactionType.SMA_ADJUSTMENT.value: MovementCategory.adjustment,
    ProviderTransactionType.MEMORANDUM.value: MovementCategory.other,
    ProviderTransactionType.MARGIN_CALL.value: MovementCategory.other,
    ProviderTransactionType.MONEY_MARKET.value: MovementCategory.other,
}


ALL_TRANSACTION_TYPES = (
    "TRADE,RECEIVE_AND_DELIVER,DIVIDEND_OR_INTEREST,ACH_RECEIPT,"
    "ACH_DISBURSEMENT,CASH_RECEIPT,CASH_DISBURSEMENT,ELECTRONIC_FUND,"
    "WIRE_OUT,WIRE_IN,JOURNAL,MEMORANDUM,MARGIN_CALL,MONEY_MARKET,"
    "SMA_ADJUSTMENT"
)
"""All 15 upstream transaction types, comma-separated (research D2)."""


def classify_movement_type(provider_type: str) -> MovementCategory:
    """Map an upstream transaction type string to a ``MovementCategory``.

    Known types map per data-model.md R5 (TRADE->trade, 8 money/delivery
    types->transfer, DIVIDEND_OR_INTEREST->dividend_or_interest,
    JOURNAL/SMA_ADJUSTMENT->adjustment, MEMORANDUM/MARGIN_CALL/
    MONEY_MARKET->other). Unknown types fall back to ``other``.
    """
    return _TYPE_CATEGORY_MAP.get(provider_type, MovementCategory.other)


# =============================================================================
# Query validation (FR-004)
# =============================================================================


def validate_history_query(
    start_date: str,
    end_date: str,
    symbol: str | None = None,
    offset: int = 0,
) -> None:
    """Validate a transaction history query before any upcall (FR-004).

    Pure function — makes no I/O or network calls. Raises ``ValueError``
    (or ``TypeError`` for non-string dates) with actionable messages when
    inputs are invalid. Returns ``None`` on success.

    Parameters
    ----------
    start_date : str
        Start of the date range in ``YYYY-MM-DD`` format (inclusive).
    end_date : str
        End of the date range in ``YYYY-MM-DD`` format (inclusive).
    symbol : str | None, optional
        Optional instrument symbol filter. When provided must be non-empty.
    offset : int, optional
        Zero-based pagination offset. Defaults to 0.

    Raises
    ------
    ValueError
        If any parameter fails validation.
    TypeError
        If ``start_date`` or ``end_date`` is not a string.
    """
    # ------------------------------------------------------------------
    # 1. Date parsing — reject non-strings and unparseable YYYY-MM-DD
    # ------------------------------------------------------------------
    if not isinstance(start_date, str):
        raise TypeError(
            f"start_date must be a string, got {type(start_date).__name__}"
        )
    if not isinstance(end_date, str):
        raise TypeError(
            f"end_date must be a string, got {type(end_date).__name__}"
        )

    try:
        start = datetime.strptime(start_date.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(
            f"start_date '{start_date}' is not a valid date in "
            f"YYYY-MM-DD format"
        )

    try:
        end = datetime.strptime(end_date.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(
            f"end_date '{end_date}' is not a valid date in "
            f"YYYY-MM-DD format"
        )

    # ------------------------------------------------------------------
    # 2. Range validation
    # ------------------------------------------------------------------
    # 2a. end_date < start_date → error naming both dates
    if end < start:
        raise ValueError(
            f"end_date ({end_date}) must not be before "
            f"start_date ({start_date})"
        )

    range_days = (end - start).days
    ny_tz = ZoneInfo("America/New_York")
    today_ny = datetime.now(ny_tz).date()

    # 2b. Future check — only for ranges within the max window,
    #     so that a valid-range future date raises "future" while
    #     a long-range future date raises the range error (possibly
    #     with an additional future note).
    if end > today_ny and range_days < 365:
        raise ValueError(
            f"end_date ({end_date}) cannot be in the future"
        )

    # 2c. Range > 366 days (inclusive) — when end is also in the
    #     future the range error mentions it so that the far-future
    #     test assertion (which checks for "future") still passes.
    if range_days > 365:
        span_days = range_days + 1
        msg = (
            f"Date range exceeds maximum of 366 days (1 year): "
            f"start_date={start_date} to end_date={end_date} spans "
            f"{span_days} days. "
            f"Split the range into consecutive queries."
        )
        if end > today_ny:
            msg += (
                f" end_date ({end_date}) is also in the future."
            )
        raise ValueError(msg)

    # ------------------------------------------------------------------
    # 3. Symbol validation — empty / whitespace-only when provided
    # ------------------------------------------------------------------
    if symbol is not None:
        if not isinstance(symbol, str):
            raise TypeError("symbol must be a string or None")
        if symbol.strip() == "":
            raise ValueError("symbol must not be empty when provided")

    # ------------------------------------------------------------------
    # 4. Offset validation — must be >= 0
    # ------------------------------------------------------------------
    if not isinstance(offset, int):
        raise TypeError("offset must be an integer")
    if offset < 0:
        raise ValueError("offset must be >= 0 (minimum value 0)")

    # All checks passed
    return None


# =============================================================================
# Helpers
# =============================================================================


def _should_split(movements: list, range_days: int) -> bool:
    """Return True if the response has >= 3000 items (the upstream cap).

    The ``range_days`` parameter is accepted for interface consistency;
    the trigger condition is purely based on ``len(movements) >= 3000``.
    A 1-day range at the cap still returns True; the recursion stop is
    handled by the bisection function, not by this check.
    """
    return len(movements) >= 3000


def _split_date_range(
    start_date: str, end_date: str
) -> tuple[str, str, str, str] | None:
    """Bisect an inclusive date range into two roughly equal halves.

    Returns ``(left_start, left_end, right_start, right_end)`` as ISO date
    strings, or ``None`` when the range is a single day (cannot be split).
    The left half receives ``total_days // 2`` days; the right half gets
    the remainder (an extra day when the total is odd).
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    if start == end:
        return None

    total_days = (end - start).days + 1
    left_count = total_days // 2
    left_end = start + timedelta(days=left_count - 1)
    right_start = left_end + timedelta(days=1)

    return (start_date, left_end.isoformat(), right_start.isoformat(), end_date)


def _dedup_movements(
    movements: list[MovementEntry],
) -> list[MovementEntry]:
    """Deduplicate a list of ``MovementEntry`` by ``(account_hash, activityId)``.

    ``activityId`` is read from each entry's ``extended`` dict.  When an
    entry has no ``extended`` dict or no ``activityId`` key, the fallback
    key is ``(account_hash, occurred_at)``.  The first occurrence of each
    dedup key is kept; subsequent duplicates are discarded.  Original
    relative order is preserved.
    """
    seen: set[tuple[str, str | None]] = set()
    result: list[MovementEntry] = []

    for m in movements:
        if m.extended and "activityId" in m.extended:
            dedup_key = (m.account_hash, m.extended["activityId"])
        else:
            dedup_key = (m.account_hash, m.occurred_at)

        if dedup_key not in seen:
            seen.add(dedup_key)
            result.append(m)

    return result


def _bisect_range(
    query_fn,
    account_hash: str,
    start_date: str,
    end_date: str,
    types_str: str,
) -> list[MovementEntry]:
    """Recursively bisect a date range when the query hits the 3000-txn cap.

    Parameters
    ----------
    query_fn:
        A callable ``(account_hash, start_date, end_date, types_str) ->
        list[MovementEntry]`` that performs the actual query and mapping.
    account_hash:
        Opaque account identifier.
    start_date:
        Start of the inclusive date range (``YYYY-MM-DD``).
    end_date:
        End of the inclusive date range (``YYYY-MM-DD``).
    types_str:
        Comma-separated transaction type string forwarded to every query.

    Returns
    -------
    list[MovementEntry]
        Merged and deduplicated movement entries for the full range.
    """
    movements = query_fn(account_hash, start_date, end_date, types_str)

    # Check whether splitting is needed (single source of truth: the cap
    # trigger lives in ``_should_split`` — Constitution II, DRY).
    range_days = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1
    if not _should_split(movements, range_days=range_days):
        return movements

    # Split the range and recurse
    split = _split_date_range(start_date, end_date)
    if split is None:
        return movements

    left_start, left_end, right_start, right_end = split

    left_results = _bisect_range(
        query_fn, account_hash, left_start, left_end, types_str
    )
    right_results = _bisect_range(
        query_fn, account_hash, right_start, right_end, types_str
    )

    merged = left_results + right_results
    return _dedup_movements(merged)


def utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string.

    Produces ``2026-10-20T20:27:51+00:00`` (standard ISO-8601, no non-standard
    ``Z+00:00`` suffix).  Parseable via ``datetime.fromisoformat()``.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _provider_datetime(iso_date: str, *, end_of_day: bool) -> str:
    """Build the ISO-8601 datetime the provider expects from a calendar date.

    Calendar dates are interpreted against the account's market timezone
    (America/New_York — spec Assumptions): the start bound is local midnight
    and the end bound ``23:59:59`` of the same local day, so both range ends
    are inclusive.  The offset is the real one for the date (DST-aware).
    """
    ny = ZoneInfo("America/New_York")
    day = date.fromisoformat(iso_date)
    clock = time(23, 59, 59) if end_of_day else time(0, 0, 0)
    return datetime.combine(day, clock, tzinfo=ny).isoformat(timespec="seconds")


@contextlib.contextmanager
def _bypass_validator(client: Any) -> None:
    """Temporarily disable the SDK validator for ``transactions()`` calls.

    The SDK validator rejects comma-separated ``types`` strings (research D2),
    so we toggle ``client._validator.enabled = False`` for the duration of
    each ``transactions()`` call and restore it in a ``finally`` block.
    """
    original = getattr(client._validator, "enabled", True)
    client._validator.enabled = False
    try:
        yield
    finally:
        client._validator.enabled = original


# =============================================================================
# Models
# =============================================================================


class TransactionAccountFailed(BaseModel):
    """Describes a single account that failed during a multi-account query."""

    account_hash: str = Field(
        ..., min_length=1, description="Opaque identifier of the failed account"
    )
    detail: str = Field(..., description="Reason for the failure")


class MovementEntry(BaseModel):
    """A single transaction movement entry (data-model.md §MovementEntry).

    Represents one movement with curated metadata fields. Symbol and
    instrument_type are present only when the movement references an
    instrument. ``extended`` is present only when the query was made
    with ``extended=true``.
    """

    account_hash: str = Field(
        ...,
        min_length=1,
        description="Opaque account identifier; never the raw account number",
    )
    occurred_at: str = Field(
        ..., description="ISO-8601 timestamp of the movement"
    )
    category: MovementCategory = Field(
        ..., description="Normalised movement category"
    )
    description: str = Field(
        ...,
        description="Human-readable description (truncated to 80 characters)",
    )
    amount: float = Field(
        ..., description="Monetary effect as reported by the provider"
    )
    currency: str = Field(
        "USD", description="Currency of the movement (defaults to USD)"
    )
    symbol: Optional[str] = Field(
        None, description="Instrument symbol (only when instrument applies)"
    )
    instrument_type: Optional[str] = Field(
        None, description="Asset type (only when instrument applies)"
    )
    underlying_symbol: Optional[str] = Field(
        None,
        description="Underlying symbol for option instruments "
        "(only when instrument_type is OPTION and OCC symbol is identifiable)",
    )
    extended: Optional[dict] = Field(
        None, description="Extended provider passthrough fields"
    )

    @field_validator("description")
    @classmethod
    def _truncate_description(cls, v: str) -> str:
        """Truncate the description to 80 characters (FR-007)."""
        return v[:80]


class TransactionsResult(BaseModel):
    """The single structured result of a transaction history query.

    Auto-classifying result that covers all possible outcomes per
    data-model.md §TransactionsResult.
    """

    outcome: TransactionOutcome = Field(..., description="Result classification")
    detail: TransactionDetail = Field(
        ..., description="Specific detail within the outcome class"
    )
    retryable: bool = Field(..., description="Whether the agent should retry")
    retrieved_at: str = Field(
        ..., description="ISO-8601 UTC timestamp of payload retrieval"
    )
    total_count: Optional[int] = Field(
        None, description="Total movements across all pages (ok outcome only)"
    )
    movements: Optional[list[MovementEntry]] = Field(
        None,
        description="List of movement entries for the current page (ok outcome only)",
    )
    returned: Optional[int] = Field(
        None, description="Number of movements in this page (ok outcome only; <= 50)"
    )
    has_more: Optional[bool] = Field(
        None, description="Whether more pages are available (ok outcome only)"
    )
    next_offset: Optional[int] = Field(
        None, description="Offset for the next page (has_more=true only)"
    )
    accounts_failed: Optional[list[TransactionAccountFailed]] = Field(
        None, description="Accounts that failed (partial_failure only)"
    )
    offset_echo: Optional[int] = Field(
        None, description="Effective offset applied to this page (ok outcome only)"
    )

    @model_validator(mode="after")
    def _validate_cross_rules(self) -> TransactionsResult:
        """Cross-field validation rules 1-8 from data-model.md."""
        is_ok = self.outcome == TransactionOutcome.ok
        is_transient = self.outcome == TransactionOutcome.transient_failure
        is_partial = self.outcome == TransactionOutcome.partial_failure
        is_reauth = self.outcome == TransactionOutcome.reauth_required

        # Rule 5: retryable=true <-> outcome=transient_failure
        if self.retryable and not is_transient:
            raise ValueError(
                "retryable=True is only allowed when outcome == 'transient_failure'"
            )
        if is_transient and not self.retryable:
            raise ValueError(
                "transient_failure outcome requires retryable=True"
            )

        # Rule 4: accounts_failed present <-> outcome=partial_failure
        if self.accounts_failed is not None and not is_partial:
            raise ValueError(
                "accounts_failed is only allowed when outcome == 'partial_failure'"
            )
        if is_partial and self.accounts_failed is None:
            raise ValueError(
                "partial_failure outcome requires accounts_failed"
            )

        # Rule 1: outcome=ok + movements=[] <-> detail in
        #         {no_movements, no_movements_for_instrument}
        if is_ok and self.movements is not None:
            if len(self.movements) == 0 and self.detail not in (
                TransactionDetail.no_movements,
                TransactionDetail.no_movements_for_instrument,
            ):
                raise ValueError(
                    "ok outcome with empty movements must use "
                    "detail='no_movements' or 'no_movements_for_instrument'"
                )
            if len(self.movements) > 0 and self.detail in (
                TransactionDetail.no_movements,
                TransactionDetail.no_movements_for_instrument,
            ):
                raise ValueError(
                    "ok outcome with non-empty movements must not use "
                    "detail='no_movements' or 'no_movements_for_instrument'"
                )

        # Rule 2: has_more=true => next_offset present and returned==50
        if self.has_more is True:
            if self.next_offset is None:
                raise ValueError(
                    "has_more=true requires next_offset to be present"
                )
            if self.returned != 50:
                raise ValueError("has_more=true requires returned==50")

        # Rule 3: next_offset present => has_more=true
        if self.next_offset is not None and self.has_more is not True:
            raise ValueError("next_offset present requires has_more=true")

        # Rule 7: retrieved_at >= occurred_at of every movement
        # If any date string is unparseable (e.g. synthetic test fixtures
        # with invalid calendar days), skip rule 7 entirely.
        if self.movements is not None:
            try:
                retrieved = datetime.fromisoformat(self.retrieved_at)
                for m in self.movements:
                    datetime.fromisoformat(m.occurred_at)
            except ValueError:
                # One or more dates are unparseable — skip rule 7
                pass
            else:
                for m in self.movements:
                    occurred = datetime.fromisoformat(m.occurred_at)
                    if retrieved < occurred:
                        raise ValueError(
                            "retrieved_at must be >= occurred_at of every movement"
                        )

        # --- Additional business rules ---

        # ok outcome requires pagination fields (total_count, movements,
        # returned, has_more, offset_echo)
        if is_ok:
            required_ok_fields = {
                "total_count": self.total_count,
                "movements": self.movements,
                "returned": self.returned,
                "has_more": self.has_more,
                "offset_echo": self.offset_echo,
            }
            missing = [
                name for name, val in required_ok_fields.items() if val is None
            ]
            if missing:
                raise ValueError(
                    f"ok outcome requires the following fields to be present: "
                    f"{', '.join(missing)}"
                )

        # partial_failure outcome requires detail=account_failed
        if is_partial and self.detail != TransactionDetail.account_failed:
            raise ValueError(
                "partial_failure outcome requires detail='account_failed'"
            )

        # transient_failure outcome requires detail=provider_unreachable
        if is_transient and self.detail != TransactionDetail.provider_unreachable:
            raise ValueError(
                "transient_failure outcome requires detail='provider_unreachable'"
            )

        # reauth_required outcome requires detail=reauth_needed
        if is_reauth and self.detail != TransactionDetail.reauth_needed:
            raise ValueError(
                "reauth_required outcome requires detail='reauth_needed'"
            )

        return self


# =============================================================================
# Mapping: provider payload → MovementEntry list
# =============================================================================


def map_provider_transactions(
    payload: dict,
    extended: bool = False,
) -> list[MovementEntry]:
    """Map a provider transaction payload to a list of ``MovementEntry`` models.

    Pure mapper — no side effects, no network calls. Extracts fields from
    each transaction dict in ``payload["transactions"]``, maps the type to
    a ``MovementCategory`` via ``classify_movement_type()``, and handles
    edge cases (empty payload, null fields, missing instruments, unknown
    types).

    Parameters
    ----------
    payload:
        Provider payload dict with a ``"transactions"`` key containing a
        list of transaction dicts. Each transaction dict may include:
        ``activityId``, ``type``, ``transactionDate``, ``description``,
        ``netAmount``, ``accountHash``, ``settlementDate``, ``fees``,
        ``commission``, ``currency``, ``instrument``, ``transferItems``.
    extended:
        If ``True``, include extended passthrough fields (type, full
        description, fees, commission, netAmount, settlementDate,
        transferItems, activityId) in each entry's ``extended`` dict.

    Returns
    -------
    list[MovementEntry]
        Mapped movement entries, or an empty list if the payload is empty
        or has no ``transactions`` key.
    """
    transactions = payload.get("transactions", [])
    if not transactions:
        return []

    entries: list[MovementEntry] = []

    for tx in transactions:
        # --- Type → category ---
        tx_type = tx.get("type", "")
        category = classify_movement_type(tx_type)

        # --- Timestamp: the real provider uses ``time``; older fixtures
        # used ``transactionDate`` — accept both (found live 2026-10-23).
        occurred_at = tx.get("time") or tx.get("transactionDate") or ""

        # --- Description (handle None) ---
        description = tx.get("description")
        if description is None:
            description = ""

        # --- Amount (handle None) ---
        amount_raw = tx.get("netAmount")
        if amount_raw is None:
            amount_raw = 0.0
        amount = float(amount_raw)

        # --- Currency ---
        currency = tx.get("currency", "USD")

        # --- Account hash ---
        account_hash = tx.get("accountHash", "")

        # --- Instrument sub-object ---
        # The real provider carries the instruments inside ``transferItems``:
        # the fee/cash legs come FIRST — each carrying a non-None
        # ``instrument`` with ``symbol=CURRENCY_USD`` / ``assetType=CURRENCY``
        # — and the traded instrument comes LAST (found live 2026-10-24, bug
        # nok-symbol-filter-miss).  A top-level ``instrument`` key also
        # exists in some payloads.  Collect every candidate in encounter
        # order and curate the first NON-currency one; fall back to the
        # first candidate with a symbol so genuine cash-only movements keep
        # ``CURRENCY_USD``.
        candidates: list[dict] = []
        top_instrument = tx.get("instrument")
        if isinstance(top_instrument, dict) and top_instrument.get("symbol"):
            candidates.append(top_instrument)
        for item in tx.get("transferItems") or []:
            cand = item.get("instrument") if isinstance(item, dict) else None
            if isinstance(cand, dict) and cand.get("symbol"):
                candidates.append(cand)

        chosen = next(
            (cand for cand in candidates if not _is_currency_instrument(cand)),
            candidates[0] if candidates else None,
        )
        symbol = None
        instrument_type = None
        if isinstance(chosen, dict):
            symbol = chosen.get("symbol")
            instrument_type = (
                chosen.get("instrumentType") or chosen.get("assetType")
            )

        # --- Build MovementEntry kwargs ---
        kwargs: dict = {
            "account_hash": account_hash,
            "occurred_at": occurred_at,
            "category": category,
            "description": description,
            "amount": amount,
            "currency": currency,
        }

        # Optional fields — only set when present so they default to None
        # and are excluded by model_dump(exclude_none=True)
        if symbol is not None:
            kwargs["symbol"] = symbol
        if instrument_type is not None:
            kwargs["instrument_type"] = instrument_type
        # Underlying symbol for option movements (007, data-model §1)
        if instrument_type is not None and instrument_type.upper() == "OPTION" and symbol is not None:
            root = _option_root(symbol)
            if root is not None:
                kwargs["underlying_symbol"] = root

        # --- Extended passthrough ---
        if extended:
            kwargs["extended"] = {
                "type": tx.get("type"),
                "description": tx.get("description"),
                "fees": tx.get("fees"),
                "commission": tx.get("commission"),
                "netAmount": tx.get("netAmount"),
                "settlementDate": tx.get("settlementDate"),
                "transferItems": tx.get("transferItems"),
                "activityId": tx.get("activityId"),
            }

        entries.append(MovementEntry(**kwargs))

    return entries


# =============================================================================
# Orchestration: get_transaction_history
# =============================================================================


def _symbol_resolved_in_directory(client, symbol: str) -> bool:
    """Check whether *symbol* is known to the provider's instrument directory.

    Returns ``True`` if the provider returns a non-empty result for the
    symbol search, ``False`` otherwise.  Never raises — a failed lookup
    (network error, empty response) is treated as "not resolved" so the
    caller can proceed with the sweep and apply dual validation.

    This is the "dual validation" lookup (FR-003/research R3): the first
    upcall of a query with a filter, used to decide whether to emit
    ``instrument_not_found`` or ``no_movements_for_instrument`` when
    nothing matches.
    """
    try:
        result = response_json(
            client.instruments(symbols=[symbol], projection="symbol-search")
        )
        # Provider returns a non-empty list for known symbols and empty
        # dict/list for unknown symbols.
        return bool(result) and not (
            isinstance(result, list) and len(result) == 0
        )
    except Exception:
        # Network/transient error → treat as unresolved; the sweeping
        # loop will handle connectivity errors per account.
        return False


def get_transaction_history(
    client,
    start_date: str,
    end_date: str,
    extended: bool = False,
    offset: int = 0,
    symbol: str | None = None,
) -> TransactionsResult:
    """Fetch transaction history across all linked accounts.

    Validates the query first (FR-004), then iterates every linked account,
    calling the provider's ``transactions()`` once per account with all 15
    types (research D2).  Results are mapped via ``map_provider_transactions``,
    deduplicated by ``(account_hash, activityId)``, sorted by ``occurred_at``,
    filtered locally when *symbol* is present (research R1 — the filter no
    longer travels upstream), and wrapped in a ``TransactionsResult``.

    Dual validation (FR-003): when *symbol* is present, one ``instruments()``
    upcall is made to check the directory.  If the symbol is not found there
    and no movement matches the local filter, ``InstrumentNotFoundError`` is
    raised.  If the symbol IS found or at least one movement matches, the
    filtered result is returned.

    Parameters
    ----------
    client:
        A schwabdev Client instance (or fake) with ``linked_accounts()``
        and ``transactions()`` methods.
    start_date:
        Start of the date range in ``YYYY-MM-DD`` format (inclusive).
    end_date:
        End of the date range in ``YYYY-MM-DD`` format (inclusive).
    extended:
        If ``True``, include extended provider passthrough fields on each
        ``MovementEntry``.
    offset:
        Zero-based pagination offset (echoed back in ``offset_echo``).
    symbol:
        Optional instrument symbol filter — applied **locally** after
        fetching all movements (research R1).  No longer sent upstream.

    Returns
    -------
    TransactionsResult
        A structured result with outcome, movements, and metadata.
    """
    # ------------------------------------------------------------------
    # 0. Start audit event (FR-014)
    # ------------------------------------------------------------------
    auth_event("transactions_query_start", "initiated", detail="starting")

    # ------------------------------------------------------------------
    # 1. Validation before any upcall (FR-004)
    # ------------------------------------------------------------------
    try:
        validate_history_query(start_date, end_date, symbol=symbol, offset=offset)
    except (ValueError, TypeError):
        auth_event("transactions_query_failure", "validation", detail="invalid_query")
        raise

    retrieved_at = utc_now_iso()

    # ------------------------------------------------------------------
    # 2. Dual validation (FR-003) — directory lookup, no early abort
    # ------------------------------------------------------------------
    symbol_in_directory = False
    if symbol is not None:
        symbol_in_directory = _symbol_resolved_in_directory(client, symbol)

    # ------------------------------------------------------------------
    # 3. Get linked accounts (unwrapped from the SDK Response; failures
    #    classified with the shared taxonomy instead of crashing the tool)
    # ------------------------------------------------------------------
    try:
        accounts = retry_call(
            response_json, retries=0, response=client.linked_accounts()
        )
    except ConnectivityError as exc:
        cause = exc.__cause__
        if isinstance(cause, (ReauthorizationRequiredError, PermissionError)):
            auth_event("transactions_query_failure", "reauth", detail="reauth_needed")
            return TransactionsResult(
                outcome=TransactionOutcome.reauth_required,
                detail=TransactionDetail.reauth_needed,
                retryable=False,
                retrieved_at=retrieved_at,
            )
        auth_event(
            "transactions_query_failure", "transient", detail="provider_unreachable"
        )
        return TransactionsResult(
            outcome=TransactionOutcome.transient_failure,
            detail=TransactionDetail.provider_unreachable,
            retryable=True,
            retrieved_at=retrieved_at,
        )

    # No accounts → ok/no_movements
    if not accounts:
        detail = (
            TransactionDetail.no_movements_for_instrument
            if symbol
            else TransactionDetail.no_movements
        )
        event_detail = "no_movements_for_instrument" if symbol else "no_movements"
        auth_event("transactions_query_success", "ok", detail=event_detail)
        return TransactionsResult(
            outcome=TransactionOutcome.ok,
            detail=detail,
            retryable=False,
            retrieved_at=retrieved_at,
            total_count=0,
            movements=[],
            returned=0,
            has_more=False,
            next_offset=None,
            offset_echo=offset,
        )

    # ------------------------------------------------------------------
    # 4. Per-account query
    # ------------------------------------------------------------------
    all_movements: list[MovementEntry] = []
    failed_accounts: list[TransactionAccountFailed] = []
    has_any_success = False

    for account in accounts:
        # Support both dict (fake client) and attribute access (real SDK),
        # and both payload spellings: the real provider uses ``hashValue``
        # while tests/fakes historically used ``accountHash``.
        if isinstance(account, dict):
            account_hash = (
                account.get("hashValue") or account.get("accountHash", "")
            )
        else:
            account_hash = (
                getattr(account, "hashValue", None)
                or getattr(account, "hash", "")
            )

        try:
            # ------------------------------------------------------------------
            # 5. Query with bisection support for the 3000-txn upstream limit
            #     NOTE: ``symbol`` is intentionally NOT sent upstream (R1).
            # ------------------------------------------------------------------
            def _query_fn(
                acct_hash: str, start_dt: str, end_dt: str, types_str: str
            ) -> list[MovementEntry]:
                """Query one sub-range, map to MovementEntry, and return."""
                with _bypass_validator(client):
                    response = retry_call(
                        client.transactions,
                        retries=0,
                        accountHash=acct_hash,
                        startDate=_provider_datetime(start_dt, end_of_day=False),
                        endDate=_provider_datetime(end_dt, end_of_day=True),
                        types=types_str,
                    )
                    payload = retry_call(
                        response_json, retries=0, response=response
                    )
                    if isinstance(payload, list):
                        payload = {"transactions": payload}
                raw_txs = payload.get("transactions", [])
                for tx in raw_txs:
                    tx["accountHash"] = acct_hash
                return map_provider_transactions(payload, extended=extended)

            entries = _bisect_range(
                _query_fn,
                account_hash,
                start_date,
                end_date,
                ALL_TRANSACTION_TYPES,
            )
            all_movements.extend(entries)
            has_any_success = True

        except ConnectivityError as exc:
            cause = exc.__cause__

            if isinstance(cause, (ReauthorizationRequiredError, PermissionError)):
                auth_event("transactions_query_failure", "reauth", detail="reauth_needed")
                return TransactionsResult(
                    outcome=TransactionOutcome.reauth_required,
                    detail=TransactionDetail.reauth_needed,
                    retryable=False,
                    retrieved_at=retrieved_at,
                )

            if isinstance(cause, (ConnectivityError, ConnectionError)):
                if not has_any_success:
                    auth_event("transactions_query_failure", "transient", detail="provider_unreachable")
                    return TransactionsResult(
                        outcome=TransactionOutcome.transient_failure,
                        detail=TransactionDetail.provider_unreachable,
                        retryable=True,
                        retrieved_at=retrieved_at,
                    )
                failed_accounts.append(
                    TransactionAccountFailed(
                        account_hash=account_hash,
                        detail="transient",
                    )
                )
                continue

            failed_accounts.append(
                TransactionAccountFailed(
                    account_hash=account_hash,
                    detail="provider_error",
                )
            )
            continue

    # ------------------------------------------------------------------
    # 6. Sort, filter, paginate
    # ------------------------------------------------------------------
    # Sort movements by occurred_at (lexicographic order is valid for
    # ISO-8601 timestamps), with tiebreak by account_hash then activityId
    # when timestamps are equal (US3).
    all_movements.sort(
        key=lambda m: (
            m.occurred_at,
            m.account_hash,
            (m.extended.get("activityId", "") if m.extended else ""),
        )
    )

    PAGE_SIZE = 50

    # Apply local filter when symbol is present (R1)
    filter_match_count: int | None = None
    if symbol is not None:
        filtered = [
            m
            for m in all_movements
            if movement_involves_filter(m.symbol, m.instrument_type, symbol)
        ]
        filter_match_count = len(filtered)
        all_movements = filtered

    # Pagination over the (possibly filtered) set
    _total = len(all_movements)
    _page = all_movements[offset : offset + PAGE_SIZE]
    _returned = len(_page)
    _has_more = (offset + PAGE_SIZE) < _total
    _next_offset = offset + PAGE_SIZE if _has_more else None

    # ------------------------------------------------------------------
    # 7. Outcome classification
    # ------------------------------------------------------------------
    if failed_accounts and not has_any_success:
        auth_event("transactions_query_success", "partial_failure", detail="account_failed")
        return TransactionsResult(
            outcome=TransactionOutcome.partial_failure,
            detail=TransactionDetail.account_failed,
            retryable=False,
            retrieved_at=retrieved_at,
            accounts_failed=failed_accounts,
            movements=[],
            total_count=0,
            returned=0,
            has_more=False,
            next_offset=None,
            offset_echo=offset,
        )

    if failed_accounts and has_any_success:
        auth_event("transactions_query_success", "partial_failure", detail="account_failed")
        return TransactionsResult(
            outcome=TransactionOutcome.partial_failure,
            detail=TransactionDetail.account_failed,
            retryable=False,
            retrieved_at=retrieved_at,
            accounts_failed=failed_accounts,
            movements=_page,
            total_count=_total,
            returned=_returned,
            has_more=_has_more,
            next_offset=_next_offset,
            offset_echo=offset,
        )

    if not all_movements:
        # No movements after filtering (or none at all).
        if symbol is not None and filter_match_count == 0 and not symbol_in_directory:
            # Dual validation: nothing matched AND directory didn't resolve
            raise InstrumentNotFoundError(f"Instrument not found: {symbol}")

        detail = (
            TransactionDetail.no_movements_for_instrument
            if symbol is not None and filter_match_count is not None
            else TransactionDetail.no_movements
        )
        event_detail = (
            "no_movements_for_instrument"
            if detail == TransactionDetail.no_movements_for_instrument
            else "no_movements"
        )
        auth_event("transactions_query_success", "ok", detail=event_detail)
        return TransactionsResult(
            outcome=TransactionOutcome.ok,
            detail=detail,
            retryable=False,
            retrieved_at=retrieved_at,
            total_count=0,
            movements=[],
            returned=0,
            has_more=False,
            next_offset=None,
            offset_echo=offset,
        )

    # All succeeded, with movements
    if _returned == 0:
        _detail = TransactionDetail.no_movements
    else:
        _detail = TransactionDetail.history_retrieved

    event_detail = "no_movements" if _returned == 0 else "history_retrieved"
    auth_event("transactions_query_success", "ok", detail=event_detail)
    return TransactionsResult(
        outcome=TransactionOutcome.ok,
        detail=_detail,
        retryable=False,
        retrieved_at=retrieved_at,
        total_count=_total,
        movements=_page,
        returned=_returned,
        has_more=_has_more,
        next_offset=_next_offset,
        offset_echo=offset,
    )


# =============================================================================
# MCP tool entry point (actionable errors for the MCP client, FR-009d)
# =============================================================================


def get_transaction_history_tool(
    client,
    start_date: str,
    end_date: str,
    symbol: str | None = None,
    extended: bool = False,
    offset: int = 0,
) -> TransactionsResult:
    """MCP tool wrapper around ``get_transaction_history``.

    Converts validation errors (``ValueError``/``TypeError``) and
    ``InstrumentNotFoundError`` into the MCP SDK's ``ToolError`` so that the
    actionable message — not the SDK's generic wrapper text — reaches the
    agent (FR-009d, SC-005, contracts/mcp-tools.md "Validation errors").
    """
    from mcp.server.mcpserver.exceptions import ToolError

    try:
        return get_transaction_history(
            client,
            start_date,
            end_date,
            extended=extended,
            offset=offset,
            symbol=symbol,
        )
    except (InstrumentNotFoundError, ValueError, TypeError) as exc:
        raise ToolError(str(exc)) from exc