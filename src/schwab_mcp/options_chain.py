"""Option chain extraction with bounding filters (feature 008).

Implements the ``get_option_chain`` domain: validated query, provider
fetch through the shared unwrapping/retry plumbing, curated mapping of the
``option_chains`` payload into the compact columnar schema, deterministic
strike/DTE/delta-window selection, and the ok / no_options_listed /
no_expirations_in_range result states.

Design sources: specs/008-extract-option-chain/{spec.md,data-model.md,
research.md,contracts/mcp-tools.md}.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from schwab_mcp.errors import ConnectivityError, ReauthorizationRequiredError
from schwab_mcp.log import auth_event
from schwab_mcp.provider import response_json
from schwab_mcp.tokens import retry_call


# =============================================================================
# Constants (data-model.md §1, research R2/R4)
# =============================================================================

CONTRACT_FIELDS: tuple[str, ...] = (
    "bid",
    "ask",
    "last",
    "mark",
    "mark_change",
    "mark_pct_change",
    "high",
    "low",
    "open",
    "close",
    "volume",
    "open_interest",
    "iv",
    "delta",
    "gamma",
    "theta",
    "vega",
    "rho",
    "theoretical_value",
    "time_value",
    "multiplier",
    "trade_time",
    "deliverable_note",
)
"""Fixed column order of each leg array (data-model.md §1 ContractFields)."""

DEFAULT_MAX_STRIKES = 50
DEFAULT_DTE_MAX = 60
DELTA_WINDOW_SIDE = 2
"""Contiguous strikes each side of the closest-delta contract -> up to 5."""

DELTA_STRIKE_COUNT_FLOOR = 100
"""Internal provider strikeCount floor when ``delta_target`` is set (R2)."""

DELTA_STRIKE_COUNT_CEILING = 200
"""Single re-fetch bound when the delta target is not bracketed (R2)."""

_CONTRACT_TYPE_MAP: dict[str, str] = {
    "both": "ALL",
    "calls": "CALL",
    "puts": "PUT",
}

# Source key per curated column (research R6 curation).  ``tradeTime`` is
# also accepted under the ``tradeTimeInLong`` spelling seen live.
_PROVIDER_KEY_MAP: dict[str, str] = {
    "bid": "bid",
    "ask": "ask",
    "last": "last",
    "mark": "mark",
    "mark_change": "markChange",
    "mark_pct_change": "markPercentChange",
    "high": "highPrice",
    "low": "lowPrice",
    "open": "openPrice",
    "close": "closePrice",
    "volume": "totalVolume",
    "open_interest": "openInterest",
    "iv": "volatility",
    "delta": "delta",
    "gamma": "gamma",
    "theta": "theta",
    "vega": "vega",
    "rho": "rho",
    "theoretical_value": "theoreticalOptionValue",
    "time_value": "timeValue",
    "multiplier": "multiplier",
    "trade_time": "tradeTime",
    "deliverable_note": "deliverableNote",
}

_INTEGER_COLUMNS = frozenset({"volume", "open_interest", "multiplier"})
"""Curated columns declared as integers (data-model §1); integral floats
from the provider (e.g. live ``multiplier=100.0``) are coerced to ``int``
without truncating non-integral values (found live 2026-10-24)."""

_PRICE_COLUMNS = frozenset(
    {
        "bid",
        "ask",
        "last",
        "mark",
        "mark_change",
        "mark_pct_change",
        "high",
        "low",
        "open",
        "close",
        "theoretical_value",
        "time_value",
    }
)
"""Curated columns rounded to 2 decimals (data-model §1)."""

_GREEK_COLUMNS = frozenset({"iv", "delta", "gamma", "theta", "vega", "rho"})
"""Curated columns rounded to 4 decimals (data-model §1)."""


# =============================================================================
# Custom exceptions
# =============================================================================


class ChainDataError(Exception):
    """Raised when a whole expiration (or map) comes without data (FR-013).

    The tool aborts with this structured error instead of returning a
    partial chain.
    """


# =============================================================================
# Query validation (FR-008)
# =============================================================================


@dataclass
class OptionChainQuery:
    """Validated input of an option chain extraction (data-model.md §1).

    ``validate()`` is pure and must run before any upcall; it raises
    ``ValueError`` (or ``TypeError`` for wrong types) with actionable
    messages quoting the data-model constraint.
    """

    symbol: str
    max_strikes: int = DEFAULT_MAX_STRIKES
    option_type: str = "both"
    delta_target: Optional[float] = None
    dte_max: Optional[int] = None

    @property
    def dte_max_effective(self) -> int:
        """The DTE cap in force: ``dte_max`` when given, else 60 (FR-005)."""
        return DEFAULT_DTE_MAX if self.dte_max is None else self.dte_max

    def validate(self) -> None:
        """Validate every filter before any upcall (FR-008).

        Raises
        ------
        TypeError
            When a parameter has the wrong type.
        ValueError
            When a parameter is out of range or outside its enum.
        """
        # --- symbol: non-empty, no internal whitespace ---
        if not isinstance(self.symbol, str):
            raise TypeError(
                "symbol must be a string "
                "(data-model §1: 'string'); "
                f"got {type(self.symbol).__name__}"
            )
        if self.symbol.strip() == "":
            raise ValueError(
                "symbol must not be empty "
                "(data-model §1: 'non-empty, no internal spaces')"
            )
        if self.symbol.strip() != self.symbol or any(
            ch.isspace() for ch in self.symbol
        ):
            raise ValueError(
                "symbol must not contain internal whitespace "
                "(data-model §1: 'non-empty, no internal spaces'); "
                f"got {self.symbol!r}"
            )

        # --- max_strikes: int >= 1 ---
        if isinstance(self.max_strikes, bool) or not isinstance(
            self.max_strikes, int
        ):
            raise TypeError(
                "max_strikes must be an integer "
                "(data-model §1: 'int'); "
                f"got {type(self.max_strikes).__name__}"
            )
        if self.max_strikes < 1:
            raise ValueError(
                "max_strikes must be >= 1 "
                "(data-model §1: '≥ 1'); "
                f"got {self.max_strikes}"
            )

        # --- option_type: enum both|calls|puts ---
        if self.option_type not in _CONTRACT_TYPE_MAP:
            raise ValueError(
                "option_type must be one of: both, calls, puts "
                "(data-model §1: 'enum value'); "
                f"got {self.option_type!r}"
            )

        # --- delta_target: None or 0 < |delta| < 1 ---
        if self.delta_target is not None:
            if isinstance(self.delta_target, bool) or not isinstance(
                self.delta_target, (int, float)
            ):
                raise TypeError(
                    "delta_target must be a number or None "
                    "(data-model §1: 'float | null'); "
                    f"got {type(self.delta_target).__name__}"
                )
            if not 0 < abs(self.delta_target) < 1:
                raise ValueError(
                    "delta_target must satisfy 0 < |delta_target| < 1 "
                    "(data-model §1: 'if present: 0 < |delta_target| < 1'); "
                    f"got {self.delta_target}"
                )

        # --- dte_max: None or int >= 1 ---
        if self.dte_max is not None:
            if isinstance(self.dte_max, bool) or not isinstance(
                self.dte_max, int
            ):
                raise TypeError(
                    "dte_max must be an integer or None "
                    "(data-model §1: 'int | null'); "
                    f"got {type(self.dte_max).__name__}"
                )
            if self.dte_max < 1:
                raise ValueError(
                    "dte_max must be >= 1 "
                    "(data-model §1: 'if present: ≥ 1'); "
                    f"got {self.dte_max}"
                )


# =============================================================================
# Provider fetch (research R1/R3)
# =============================================================================


def fetch_option_chain(
    client: Any,
    query: OptionChainQuery,
    strike_count: int | None = None,
) -> dict:
    """Fetch the raw provider chain payload for *query*.

    Validates first (FR-008 — no upcall before validation), then calls
    ``client.option_chains()`` with the mapped filters:

    - ``contractType``: ``both→ALL``, ``calls→CALL``, ``puts→PUT``
    - ``strikeCount``: *strike_count* override or ``query.max_strikes``
    - ``fromDate``: today; ``toDate``: today + ``dte_max_effective``
      (DTE in calendar days — research R3)
    - ``includeUnderlyingQuote=True`` (underlying price reference, R1)

    Wrapped in ``tokens.retry_call`` + ``provider.response_json`` (shared
    unwrapping and error taxonomy, research R5).  Returns the raw payload
    dict; provider failures surface as ``ConnectivityError`` (with the
    taxonomy class as ``__cause__``), ``ReauthorizationRequiredError`` or
    ``ValueError`` per the shared mapping.
    """
    query.validate()

    count = query.max_strikes if strike_count is None else strike_count
    today = date.today()
    from_date = today.isoformat()
    to_date = (today + timedelta(days=query.dte_max_effective)).isoformat()

    response = retry_call(
        client.option_chains,
        0,
        query.symbol,
        contractType=_CONTRACT_TYPE_MAP[query.option_type],
        strikeCount=count,
        fromDate=from_date,
        toDate=to_date,
        includeUnderlyingQuote=True,
    )

    # The provider rejects symbols with no listed options with HTTP 400
    # (found live 2026-10-24) instead of empty maps.  After query
    # validation no other parameter can trigger a 400, so this is the live
    # shape of "no options listed" — report the structured no-data state
    # instead of a transport error (FR-009, contract §4).
    if getattr(response, "status_code", None) == 400:
        return {}

    return retry_call(response_json, 0, response=response)


# =============================================================================
# Curated serialization (research R4/R6)
# =============================================================================


def _trade_time_value(raw: Any) -> Any:
    """Normalise the provider trade timestamp to an ISO-8601 UTC string.

    Epoch milliseconds (the ``tradeTime``/``tradeTimeInLong`` live shape)
    are converted; strings pass through; anything else keeps its value.
    A zero epoch means "never traded" (the live provider sends
    ``tradeTimeInLong=0`` for those contracts — found live 2026-10-24)
    and maps to ``None`` (FR-007: never invent data).
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if raw == 0:
            return None
        return datetime.fromtimestamp(
            raw / 1000, timezone.utc
        ).isoformat(timespec="seconds")
    return raw


def serialize_leg(contract: dict) -> list:
    """Serialize one provider contract as a positional ``CONTRACT_FIELDS`` array.

    Column order is the fixed ``CONTRACT_FIELDS`` layout (data-model §1).
    Deterministic rounding (research R4): prices/values 2 decimals, greeks
    and IV 4 decimals, ``volume``/``open_interest``/``multiplier`` unrounded.
    ``trade_time`` becomes ISO-8601 UTC; ``deliverable_note`` passes through.
    A missing source field yields an explicit ``None`` in its column
    (FR-007) — values are never invented.  Trailing ``None`` columns are
    trimmed (contract §2 allows shorter arrays).
    """
    values: list = []
    for name in CONTRACT_FIELDS:
        source_key = _PROVIDER_KEY_MAP[name]
        raw = contract.get(source_key)
        if raw is None and name == "trade_time":
            raw = contract.get("tradeTimeInLong")
        if raw is None:
            values.append(None)
        elif name == "trade_time":
            values.append(_trade_time_value(raw))
        elif name in _INTEGER_COLUMNS:
            values.append(
                int(raw) if isinstance(raw, float) and raw.is_integer() else raw
            )
        elif name in _PRICE_COLUMNS:
            values.append(round(float(raw), 2))
        elif name in _GREEK_COLUMNS:
            values.append(round(float(raw), 4))
        else:
            values.append(raw)
    while values and values[-1] is None:
        values.pop()
    return values


# =============================================================================
# Mapping and selection (data-model §2–§3)
# =============================================================================


def _included_legs(option_type: str) -> tuple[str, ...]:
    """Leg kinds included by ``option_type``, in ``call``/``put`` order."""
    if option_type == "both":
        return ("call", "put")
    return ("call",) if option_type == "calls" else ("put",)


def _expiration_date(map_key: str) -> str:
    """Normalise an ``*ExpDateMap`` key to its ``YYYY-MM-DD`` date.

    The live provider keys carry a suffix (``"2026-10-26:2"`` — found live
    2026-10-24); older fixtures use the plain date.  Both normalise to the
    date part so maps compare and parse consistently.
    """
    return map_key.split(":")[0]


def _leg_map(payload: dict, kind: str) -> dict:
    """Return ``{expiration_date: {key: contract}}`` for one leg kind.

    Map keys are normalised via :func:`_expiration_date`.  An
    absent/``None``/empty map normalises to ``{}``.
    """
    key = "callExpDateMap" if kind == "call" else "putExpDateMap"
    raw = payload.get(key)
    if not isinstance(raw, dict) or not raw:
        return {}
    return {_expiration_date(map_key): entries for map_key, entries in raw.items()}


def _iter_contracts(entries: dict) -> list[tuple[float | None, dict]]:
    """Normalise one ``*ExpDateMap`` entry into ``(strike, contract)`` pairs.

    Two provider shapes are supported (the live one, found live 2026-10-24,
    and the dict-shaped fixtures):

    - ``{key: {contract}}`` — the contract dict carries ``strikePrice``;
    - ``{strike_string: [contract, ...]}`` — list-valued entries keyed by
      the strike; the first dict of the list is the (SINGLE-strategy) leg.

    The strike falls back to the entry key when ``strikePrice`` is absent.
    """
    pairs: list[tuple[float | None, dict]] = []
    for entry_key, value in entries.items():
        if isinstance(value, dict):
            candidates = [value]
        elif isinstance(value, list):
            candidates = [item for item in value if isinstance(item, dict)]
        else:
            continue
        key_strike: float | None = None
        try:
            key_strike = float(entry_key)
        except (TypeError, ValueError):
            key_strike = None
        for contract in candidates:
            strike = contract.get("strikePrice")
            if strike is None:
                strike = key_strike
            if strike is None:
                continue
            pairs.append((float(strike), contract))
    return pairs


def _check_partial_chain(leg_maps: dict[str, dict], legs: tuple[str, ...]) -> None:
    """FR-013: abort on a whole expiration (or map) without data.

    For every included leg kind and every date in the union of the included
    maps' date keys, that kind's map must carry a non-empty contract dict.
    Date-level asymmetry is a partial chain (spec clarification: "structured
    error without partial chain"); strike-level holes are legitimate.
    """
    non_empty = {kind: leg_maps[kind] for kind in legs if leg_maps.get(kind)}
    if not non_empty:
        return
    for kind in legs:
        if not leg_maps.get(kind):
            raise ChainDataError(
                f"whole expiration map missing for {kind} contracts "
                f"while other legs carry data (FR-013: no partial chain)"
            )
    dates: set[str] = set()
    for mapping in non_empty.values():
        dates.update(mapping.keys())
    for exp_date in sorted(dates):
        for kind in legs:
            entries = leg_maps[kind].get(exp_date)
            if not entries:
                raise ChainDataError(
                    f"expiration {exp_date} has no {kind} data "
                    f"(FR-013: no partial chain)"
                )


def _select_strike_window(
    strikes: list[float], atm_strike: float, max_strikes: int
) -> list[float]:
    """Symmetric window around *atm_strike* (data-model §3).

    The up-to-*max_strikes* nearest strikes ``<= atm_strike`` (ATM included
    if it exists) union the up-to-*max_strikes* nearest strikes
    ``>= atm_strike`` (ATM included if it exists); fewer available → all.
    """
    below = [s for s in strikes if s <= atm_strike][-max_strikes:]
    above = [s for s in strikes if s >= atm_strike][:max_strikes]
    return sorted(set(below) | set(above))


def _select_delta_window(
    contracts_by_strike: dict[float, dict],
    delta_target: float,
) -> list[float]:
    """Delta window for one type (FR-004, data-model §3, research R2).

    The anchor is the contract minimizing ``abs(abs(delta) - delta_target)``
    over the non-null deltas of the type (ties resolve to the lower strike);
    the window is the anchor's index in the type's ascending-strike
    sequence ± ``DELTA_WINDOW_SIDE`` contiguous strikes each side — up to 5,
    clipped to what exists.  Never invents strikes; ``max_strikes`` does not
    reduce this window.
    """
    anchored = [
        (strike, contract)
        for strike, contract in contracts_by_strike.items()
        if contract.get("delta") is not None
    ]
    if not anchored:
        return []
    anchor_strike = min(
        anchored,
        key=lambda item: (abs(abs(item[1]["delta"]) - delta_target), item[0]),
    )[0]
    strikes_sorted = sorted(contracts_by_strike)
    index = strikes_sorted.index(anchor_strike)
    low = max(0, index - DELTA_WINDOW_SIDE)
    high = min(len(strikes_sorted), index + DELTA_WINDOW_SIDE + 1)
    return strikes_sorted[low:high]


def _delta_bracketed(payload: dict, query: OptionChainQuery) -> bool:
    """Whether the fetched payload brackets the delta target (research R2).

    Per included leg type, the target is bracketed when the fetched
    ``abs(delta)`` values are not all above and not all below it.  A type
    with no delta values at all is ignored; an entirely missing included
    map is left to the FR-013 partial-chain check.
    """
    target = query.delta_target
    if target is None:
        return True
    for kind in _included_legs(query.option_type):
        values = [
            abs(contract["delta"])
            for entries in _leg_map(payload, kind).values()
            for _strike, contract in _iter_contracts(entries)
            if contract.get("delta") is not None
        ]
        if not values:
            continue
        if all(v > target for v in values) or all(v < target for v in values):
            return False
    return True


def _atm_strike(strikes: list[float], underlying_price: float | None) -> float:
    """Strike closest to ``underlying_price``; ties resolve to the lower.

    Without an underlying price the middle of the ladder is used as the
    deterministic reference.
    """
    if underlying_price is None:
        return strikes[len(strikes) // 2]
    return min(strikes, key=lambda s: (abs(s - underlying_price), s))


def _map_expirations(
    payload: dict,
    query: OptionChainQuery,
    today: date,
) -> list[dict]:
    """Build the curated ``expirations`` list from the provider payload.

    Applies the DTE filter, per-type strike windows (or the delta window —
    TODO(T016): delta selection lands with US2) and the strike-level leg
    union.  Returns expirations sorted ascending by date, strikes ascending.
    """
    legs = _included_legs(query.option_type)
    leg_maps = {
        "call": _leg_map(payload, "call"),
        "put": _leg_map(payload, "put"),
    }
    underlying_price = payload.get("underlyingPrice")
    if underlying_price is None:
        underlying = payload.get("underlying") or {}
        underlying_price = underlying.get("last")

    dates: set[str] = set()
    for kind in legs:
        dates.update(leg_maps[kind].keys())

    expirations: list[dict] = []
    for exp_date in sorted(dates):
        dte = (date.fromisoformat(exp_date) - today).days
        if dte > query.dte_max_effective:
            continue

        contracts_by_kind: dict[str, dict[float, dict]] = {}
        for kind in legs:
            entries = leg_maps[kind].get(exp_date) or {}
            contracts_by_kind[kind] = dict(_iter_contracts(entries))

        all_strikes = sorted(
            {s for by_strike in contracts_by_kind.values() for s in by_strike}
        )
        atm = _atm_strike(all_strikes, underlying_price)

        selected: dict[str, set[float]] = {}
        for kind in legs:
            kind_strikes = sorted(contracts_by_kind[kind])
            if query.delta_target is not None:
                selected[kind] = set(
                    _select_delta_window(
                        contracts_by_kind[kind], query.delta_target
                    )
                )
            else:
                selected[kind] = set(
                    _select_strike_window(kind_strikes, atm, query.max_strikes)
                )

        rows: list[dict] = []
        row_strikes = sorted(set().union(*selected.values()))
        for strike in row_strikes:
            row: dict[str, Any] = {"strike": strike}
            for kind in legs:
                contract = contracts_by_kind[kind].get(strike)
                if contract is not None and strike in selected[kind]:
                    row[kind] = serialize_leg(contract)
            rows.append(row)

        expirations.append(
            {
                "expiration_date": exp_date,
                "dte": dte,
                "atm_strike": atm,
                "strikes": rows,
            }
        )
    return expirations


def _filters_echo(query: OptionChainQuery) -> dict:
    """Effective-query echo (contract §2), including ``dte_max_effective``."""
    return {
        "max_strikes": query.max_strikes,
        "option_type": query.option_type,
        "delta_target": query.delta_target,
        "dte_max_requested": query.dte_max,
        "dte_max_effective": query.dte_max_effective,
    }


def _result_meta(query: OptionChainQuery, payload: dict) -> dict:
    """ChainMeta fields shared by every result state (FR-010)."""
    return {
        "symbol": query.symbol,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def build_chain_result(
    payload: dict,
    query: OptionChainQuery,
    *,
    today: date | None = None,
) -> dict:
    """Map a raw provider payload to the curated response (pure, no I/O).

    States (data-model §4): ``ok`` (full curated chain),
    ``no_options_listed`` (no expiration maps at all),
    ``no_expirations_in_range`` (the DTE cap excludes every expiration).
    Raises :class:`ChainDataError` when a whole expiration (or map) comes
    without data — FR-013, never a partial chain.
    """
    query.validate()
    today = today if today is not None else date.today()

    legs = _included_legs(query.option_type)
    leg_maps = {
        "call": _leg_map(payload, "call"),
        "put": _leg_map(payload, "put"),
    }
    meta = _result_meta(query, payload)

    if not leg_maps["call"] and not leg_maps["put"]:
        return {
            "outcome": "no_options_listed",
            "detail": "no_options_listed",
            **meta,
        }

    _check_partial_chain(leg_maps, legs)

    expirations = _map_expirations(payload, query, today)

    if not expirations:
        return {
            "outcome": "no_expirations_in_range",
            "detail": (
                "no_expirations_in_range: "
                f"dte_max_effective={query.dte_max_effective} "
                "excludes all expirations"
            ),
            **meta,
            "filters": _filters_echo(query),
            "expirations": [],
        }

    underlying_price = payload.get("underlyingPrice")
    if underlying_price is None:
        underlying = payload.get("underlying") or {}
        underlying_price = underlying.get("last")

    return {
        "outcome": "ok",
        "detail": "chain_retrieved",
        **meta,
        "data_state": "delayed" if payload.get("isDelayed") else "realtime",
        "underlying_price": underlying_price,
        "filters": _filters_echo(query),
        "contract_fields": list(CONTRACT_FIELDS),
        "expirations": expirations,
    }


# =============================================================================
# Orchestration: get_option_chain
# =============================================================================


def get_option_chain(
    client: Any,
    symbol: str,
    max_strikes: int = DEFAULT_MAX_STRIKES,
    option_type: str = "both",
    delta_target: float | None = None,
    dte_max: int | None = None,
    extended: bool = False,
) -> dict:
    """Extract the option chain of *symbol* within the bounding filters.

    One invocation returns the whole chain inside the requested limits —
    no pagination (FR-011/SC-004).  Validation runs before any upcall
    (FR-008); a whole expiration without data aborts with
    :class:`ChainDataError` (FR-013).  ``extended=True`` adds the raw
    provider payload under ``"provider"`` (pattern 003/006).
    """
    auth_event("options_chain_query_start", "initiated", detail="starting")

    query = OptionChainQuery(
        symbol=symbol,
        max_strikes=max_strikes,
        option_type=option_type,
        delta_target=delta_target,
        dte_max=dte_max,
    )
    try:
        query.validate()
    except (ValueError, TypeError):
        auth_event(
            "options_chain_query_failure", "validation", detail="invalid_query"
        )
        raise

    # Internal strikeCount expansion (research R2): with a delta target the
    # fetch asks max(max_strikes, 100) so the target zone is inside the
    # returned window, with exactly one re-fetch up to 200 when the target
    # is not bracketed (T016).
    try:
        if query.delta_target is not None:
            payload = fetch_option_chain(
                client,
                query,
                strike_count=max(query.max_strikes, DELTA_STRIKE_COUNT_FLOOR),
            )
            if not _delta_bracketed(payload, query):
                payload = fetch_option_chain(
                    client,
                    query,
                    strike_count=DELTA_STRIKE_COUNT_CEILING,
                )
        else:
            payload = fetch_option_chain(client, query)
        result = build_chain_result(payload, query)
    except ChainDataError:
        auth_event(
            "options_chain_query_failure", "error", detail="chain_data_error"
        )
        raise
    except ReauthorizationRequiredError:
        auth_event(
            "options_chain_query_failure", "reauth", detail="reauth_needed"
        )
        raise
    except ConnectivityError:
        auth_event(
            "options_chain_query_failure",
            "transient",
            detail="provider_unreachable",
        )
        raise
    except ValueError:
        auth_event(
            "options_chain_query_failure", "error", detail="provider_error"
        )
        raise

    if extended:
        result["provider"] = payload

    auth_event(
        "options_chain_query_success",
        result["outcome"],
        detail=result["detail"],
    )
    return result


# =============================================================================
# MCP tool entry point (actionable errors for the MCP client)
# =============================================================================


def get_option_chain_tool(
    client: Any,
    symbol: str,
    max_strikes: int = DEFAULT_MAX_STRIKES,
    option_type: str = "both",
    delta_target: float | None = None,
    dte_max: int | None = None,
    extended: bool = False,
) -> dict:
    """MCP tool wrapper around :func:`get_option_chain`.

    Converts validation errors (``ValueError``/``TypeError``) and
    :class:`ChainDataError` into the MCP SDK's ``ToolError`` so that the
    actionable message — not a generic wrapper — reaches the agent
    (pattern: ``transactions.get_transaction_history_tool``).
    """
    from mcp.server.mcpserver.exceptions import ToolError

    try:
        return get_option_chain(
            client,
            symbol,
            max_strikes=max_strikes,
            option_type=option_type,
            delta_target=delta_target,
            dte_max=dte_max,
            extended=extended,
        )
    except (ChainDataError, ValueError, TypeError) as exc:
        raise ToolError(str(exc)) from exc
