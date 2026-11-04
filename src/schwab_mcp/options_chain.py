"""Option chain extraction with bounding filters (feature 008).

Implements the ``get_option_chain`` domain: validated query, provider
fetch through the shared unwrapping/retry plumbing, curated mapping of the
``option_chains`` payload into the compact columnar schema, deterministic
strike/DTE/delta-window selection, and the ok / no_options_listed /
no_expirations_in_range result states.

Also implements the ``get_option_expiration_chain`` domain (feature 012):
the cheap expiration-chain listing of one underlying (expiration date, DTE,
settlement type) with the same DTE-ceiling semantics.

Design sources: specs/008-extract-option-chain/{spec.md,data-model.md,
research.md,contracts/mcp-tools.md};
specs/012-option-expiration-list/{spec.md,data-model.md,research.md,
contracts/mcp-tools.md}.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from schwab_mcp.errors import ConnectivityError, ReauthorizationRequiredError
from schwab_mcp.log import auth_event
from schwab_mcp.provider import response_json, trade_time_value
from schwab_mcp.symbols import classify_underlying
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


class ProviderBodyLimitError(ChainDataError):
    """Raised when the provider rejects the chain response body as too
    large (bug spx-chain-body-limit).

    Observed live 2026-11-03: a ``$SPX`` chain at ``strikeCount=200``
    takes ~44 s to assemble server-side and is then rejected by the API
    gateway with ``502 {"fault":{"faultstring":"Body buffer overflow",
    "detail":{"errorcode":"protocol.http.TooBigBody"}}}``.  This is a
    deterministic request-shape fault, NOT transient connectivity — it
    must never surface as :class:`schwab_mcp.errors.ConnectivityError`
    (whose message tells the user to check connectivity).
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

        # --- symbol grammar: the package's single source of truth (bug
        # duplicate-symbol-validation).  The chain endpoints serve
        # underlyings, so the raw symbol is classified through
        # ``classify_underlying`` (slash-form and case tolerant); an
        # off-grammar symbol is rejected here instead of surfacing the
        # provider's HTTP 400 as a misleading ``no_options_listed``.
        classified = classify_underlying(self.symbol)
        if classified is None:
            raise ValueError(
                "symbol matches no supported grammar "
                "(equity/ETF like AAPL or BRK.B, or index like $SPX "
                "— schwab_mcp.symbols.classify_underlying); "
                f"got {self.symbol!r}"
            )
        if classified[0] == "option":
            raise ValueError(
                "symbol must be an underlying (equity/ETF or index), "
                "not an option contract — the chain endpoints serve "
                f"underlyings; got {self.symbol!r}"
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


def _is_no_options_response(response: Any) -> bool:
    """Whether *response* is the provider's HTTP-400 "no options listed".

    The provider rejects symbols with no listed options with HTTP 400
    (found live 2026-10-24) instead of empty maps.  After query
    validation no other parameter can trigger a 400, so this is the live
    shape of "no options listed" — a structured no-data state, not a
    transport error (FR-009, contract §4).  Shared verbatim by
    :func:`fetch_option_chain` and :func:`_fetch_expiration_chain`
    (TD-008 site 2).
    """
    return getattr(response, "status_code", None) == 400


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

    # Post-validation HTTP 400 = "no options listed" (see
    # _is_no_options_response) — report the structured no-data state
    # instead of a transport error (FR-009, contract §4).
    if _is_no_options_response(response):
        return {}

    # The provider gateway rejects oversized chain responses with
    # 502 + "Body buffer overflow" (protocol.http.TooBigBody) after a
    # long (~44 s for $SPX at strikeCount=200) server-side assembly — a
    # deterministic request-shape fault, not transient connectivity (bug
    # spx-chain-body-limit).  Detect it before the shared 5xx mapping so
    # callers can degrade (delta ceiling re-fetch) or report an actionable
    # error (explicit oversized max_strikes).
    if getattr(response, "status_code", None) == 502:
        body = getattr(response, "text", "") or ""
        if (
            "protocol.http.TooBigBody" in body
            or "Body buffer overflow" in body
        ):
            raise ProviderBodyLimitError(
                f"provider rejected the chain response body as too large "
                f"(requested strikeCount={count}); reduce max_strikes or "
                f"narrow dte_max for this symbol"
            )

    return retry_call(response_json, 0, response=response)


# =============================================================================
# Curated serialization (research R4/R6)
# =============================================================================


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
            values.append(trade_time_value(raw))
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

    ``delta_target`` is compared by magnitude (``abs``): users pass the
    signed provider delta convention (puts negative, calls positive), so
    the anchor matches ``|delta| ≈ |target|`` regardless of sign (bug
    delta-target-sign-bracketing: the raw negative value anchored the
    window on the deepest-OTM contract).
    """
    delta_target = abs(delta_target)
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

    The comparison uses ``abs(delta_target)``: deltas are compared by
    magnitude against the target's magnitude (users pass the signed
    provider convention — puts negative).  With the raw negative value
    every payload was classified unbracketed, triggering the
    ``strikeCount=200`` ceiling re-fetch on every negative-target call
    (bug delta-target-sign-bracketing).
    """
    target = query.delta_target
    if target is None:
        return True
    target = abs(target)
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


def _underlying_price(payload: dict) -> float | None:
    """Underlying reference price: ``underlyingPrice`` with the
    ``underlying.last`` fallback (research R1).  ``None`` when the payload
    carries neither — values are never invented (FR-007).  Shared by the
    ``ok`` result state and the ATM selection (TD-008 site 3)."""
    price = payload.get("underlyingPrice")
    if price is None:
        underlying = payload.get("underlying") or {}
        price = underlying.get("last")
    return price


def _map_expirations(
    leg_maps: dict[str, dict],
    query: OptionChainQuery,
    today: date,
    underlying_price: float | None,
) -> list[dict]:
    """Build the curated ``expirations`` list from *leg_maps*.

    ``leg_maps`` and ``underlying_price`` are computed once by
    :func:`build_chain_result` and passed down, so the normalization
    cannot diverge between the no-data gate and the mapping (TD-008
    sites 3/4).  Applies the DTE filter, per-type strike windows (or the
    delta window) and the strike-level leg union.  Returns expirations
    sorted ascending by date, strikes ascending.
    """
    legs = _included_legs(query.option_type)

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


def _result_meta(query: OptionChainQuery) -> dict:
    """ChainMeta fields shared by every result state of both tools
    (FR-010).  No payload input — the meta depends on the query only
    (TD-008 site 7)."""
    return {
        "symbol": query.symbol,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _no_expirations_detail(query: OptionChainQuery) -> str:
    """Detail string of the ``no_expirations_in_range`` state, shared
    verbatim by both tools (TD-008 site 5); pinned by tests (contract §2)."""
    return (
        "no_expirations_in_range: "
        f"dte_max_effective={query.dte_max_effective} "
        "excludes all expirations"
    )


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
    underlying_price = _underlying_price(payload)
    meta = _result_meta(query)

    if not leg_maps["call"] and not leg_maps["put"]:
        return {
            "outcome": "no_options_listed",
            "detail": "no_options_listed",
            **meta,
        }

    _check_partial_chain(leg_maps, legs)

    expirations = _map_expirations(leg_maps, query, today, underlying_price)

    if not expirations:
        return {
            "outcome": "no_expirations_in_range",
            "detail": _no_expirations_detail(query),
            **meta,
            "filters": _filters_echo(query),
            "expirations": [],
        }

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


def _fetch_chain_payload(client: Any, query: OptionChainQuery) -> dict:
    """Fetch the raw chain payload with the delta strikeCount expansion.

    With a delta target the fetch asks ``max(max_strikes, 100)`` so the
    target zone is inside the returned window, with exactly one re-fetch
    up to 200 when the target is not bracketed (T016, research R2).  When
    the ceiling re-fetch exceeds the provider response body limit (bug
    spx-chain-body-limit, observed live on $SPX) the request degrades to
    the floor payload: the available contracts closest to the target.
    Extracted from :func:`get_option_chain` so the degradation logic is a
    named seam instead of nested try/except (TD-008 site 8).
    """
    if query.delta_target is None:
        return fetch_option_chain(client, query)

    payload = fetch_option_chain(
        client,
        query,
        strike_count=max(query.max_strikes, DELTA_STRIKE_COUNT_FLOOR),
    )
    if _delta_bracketed(payload, query):
        return payload
    try:
        return fetch_option_chain(
            client,
            query,
            strike_count=DELTA_STRIKE_COUNT_CEILING,
        )
    except ProviderBodyLimitError:
        auth_event(
            "options_chain_query_degraded",
            "degraded",
            detail="provider_body_limit",
        )
        return payload


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

    # Error mapping (TD-008 site 1): near-mirrored in
    # get_option_expiration_chain, which omits ChainDataError — that path
    # fetches no chain data.  Kept as explicit near-duplicates (KISS): the
    # per-tool auth_event prefixes and this one-block difference are the
    # only variation.
    try:
        payload = _fetch_chain_payload(client, query)
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

    Converts validation errors (``ValueError``/``TypeError``),
    :class:`ChainDataError` and the auth-taxonomy errors
    (:class:`ConnectivityError`, :class:`ReauthorizationRequiredError`) into
    the MCP SDK's ``ToolError`` so that the actionable message — not the
    SDK's generic ``UnexpectedToolError`` wrapper — reaches the agent
    (bug domain-errors-swallowed; helper:
    ``tool_errors.raise_classified_tool_error``).
    """
    from schwab_mcp.errors import AuthError
    from schwab_mcp.tool_errors import raise_classified_tool_error

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
    except (AuthError, ChainDataError, ValueError, TypeError) as exc:
        raise_classified_tool_error(exc)


# =============================================================================
# Option expiration list (feature 012: get_option_expiration_chain)
# =============================================================================


def _fetch_expiration_chain(client: Any, query: OptionChainQuery) -> dict:
    """Fetch the raw provider expiration-chain payload for *query*.

    Validates first (no upcall before validation — FR-008 semantics), then
    calls ``client.option_expiration_chain(symbol)`` through
    ``tokens.retry_call`` + ``provider.response_json`` (shared unwrapping
    and error taxonomy, research R3).  The SDK endpoint takes no filter
    parameters (research R1), so the DTE ceiling is applied client-side
    after fetch.  HTTP 400 after validation is the live "no options
    listed" shape (research R6, the 008 finding of 2026-10-24) and maps to
    ``{}``.  Provider failures surface as ``ConnectivityError`` (with the
    taxonomy class as ``__cause__``), ``ReauthorizationRequiredError`` or
    ``ValueError`` per the shared mapping.
    """
    query.validate()

    response = retry_call(client.option_expiration_chain, 0, query.symbol)

    # See _is_no_options_response: post-validation a 400 can only mean
    # the symbol has no listed options — a structured no-data state, not
    # a transport error.
    if _is_no_options_response(response):
        return {}

    return retry_call(response_json, 0, response=response)


def _parse_expiration_date(raw: Any) -> date | None:
    """Parse a provider expiration date string; ``None`` when absent or
    unparseable (the entry is kept with a null ``dte`` — never silently
    dropped, research R6).  Shared by the entry mapping and the sort key,
    which receives the date already parsed by :func:`_map_expiration_list`
    — each expiration date is parsed exactly once (TD-008 site 6)."""
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _expiration_entry(entry: dict, dte: int | None) -> dict:
    """Map one provider expiration entry to the curated shape (data-model §2).

    ``expiration_date`` (provider ``expirationDate``) and ``settlement_type``
    (provider ``settlementType``) pass through unmodified; a missing field
    yields an explicit ``None`` — values are never invented (research R6).
    ``dte`` is calendar days from *today* computed locally by the caller
    (via :func:`_parse_expiration_date`): the provider's
    ``daysToExpiration`` is deliberately ignored (research R4, one DTE
    definition across both tools).  An unparseable date keeps the entry with
    a null ``dte`` — entries are never silently dropped (research R6).
    """
    return {
        "expiration_date": entry.get("expirationDate"),
        "dte": dte,
        "settlement_type": entry.get("settlementType"),
    }


def _expiration_sort_key(
    item: tuple[date | None, int, dict],
) -> tuple[int, int, int]:
    """Ascending ``expiration_date`` with provider order for ties (§2).

    The parsed date arrives pre-computed from :func:`_map_expiration_list`
    (TD-008 site 6 — no re-parse at sort time).  Entries without a
    parseable date cannot be ordered against dated ones and sort last,
    keeping provider order among themselves.
    """
    parsed, index, _entry = item
    if parsed is None:
        return (1, 0, index)
    return (0, parsed.toordinal(), index)


def _map_expiration_list(
    payload: dict,
    query: OptionChainQuery,
    today: date,
) -> list[dict]:
    """Build the curated ``expirations`` list from the provider payload.

    Every provider entry is mapped (never dropped), the
    ``dte ≤ dte_max_effective`` ceiling is applied (an entry whose ``dte``
    is unknown cannot be proven out of range and is kept), and the result
    is sorted per :func:`_expiration_sort_key`.  Same-date entries are kept
    as separate rows distinguished by ``settlement_type`` — the data-model
    §2 identity rule forbids merging or deduplication.
    """
    entries = payload.get("expirationList")
    if not isinstance(entries, list):
        return []
    kept: list[tuple[date | None, int, dict]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        parsed = _parse_expiration_date(entry.get("expirationDate"))
        dte: int | None = None if parsed is None else (parsed - today).days
        if dte is not None and dte > query.dte_max_effective:
            continue
        kept.append((parsed, index, _expiration_entry(entry, dte)))
    return [entry for _parsed, _index, entry in sorted(kept, key=_expiration_sort_key)]


def _expiration_filters_echo(query: OptionChainQuery) -> dict:
    """Applied-ceiling echo (data-model §2): ``dte_max_requested``/``effective``."""
    return {
        "dte_max_requested": query.dte_max,
        "dte_max_effective": query.dte_max_effective,
    }


def build_expiration_result(
    payload: dict,
    query: OptionChainQuery,
    today: date | None = None,
) -> dict:
    """Map a raw provider expiration-chain payload to the result (pure).

    States (data-model §3): ``ok`` (at least one expiration inside the
    ceiling), ``no_expirations_in_range`` (expirations exist but the ceiling
    excludes every one — retryable, the detail names the effective cap),
    ``no_options_listed`` (absent/empty ``expirations``, including the live
    HTTP-400 shape ``{}`` — the underlying has no listed options).
    """
    query.validate()
    today = today if today is not None else date.today()
    meta = _result_meta(query)

    if not payload.get("expirationList"):
        return {
            **meta,
            "outcome": "no_options_listed",
            "detail": "no_options_listed: the underlying has no listed options",
            "retryable": False,
            "expirations": [],
        }

    expirations = _map_expiration_list(payload, query, today)

    if not expirations:
        return {
            **meta,
            "outcome": "no_expirations_in_range",
            "detail": _no_expirations_detail(query),
            "retryable": True,
            "filters": _expiration_filters_echo(query),
            "expirations": [],
            "expiration_count": 0,
        }

    return {
        **meta,
        "outcome": "ok",
        "detail": None,
        "retryable": None,
        "filters": _expiration_filters_echo(query),
        "expirations": expirations,
        "expiration_count": len(expirations),
    }


def get_option_expiration_chain(
    client: Any,
    symbol: str,
    dte_max: int | None = None,
    extended: bool = False,
) -> dict:
    """List the upcoming expirations of *symbol* in one cheap call.

    Returns the curated expiration list (date, DTE in calendar days,
    settlement type) inside the same DTE-ceiling semantics as
    :func:`get_option_chain` (``dte_max`` ≥ 1 replaces the 60-day default
    and is echoed as ``dte_max_effective``).  Exactly one provider
    invocation per request (SC-004); no strikes, quotes, or greeks
    (FR-006).  Validation runs before any upcall; ``extended=True`` adds
    the raw provider payload under ``"provider"`` (pattern 003/006/008).
    """
    auth_event("expiration_chain_query_start", "initiated", detail="starting")

    query = OptionChainQuery(symbol=symbol, dte_max=dte_max)
    try:
        query.validate()
    except (ValueError, TypeError):
        auth_event(
            "expiration_chain_query_failure", "validation", detail="invalid_query"
        )
        raise

    # Error mapping — near-mirror of get_option_chain's (TD-008 site 1);
    # this path cannot raise ChainDataError (no chain data is fetched).
    try:
        payload = _fetch_expiration_chain(client, query)
        result = build_expiration_result(payload, query)
    except ReauthorizationRequiredError:
        auth_event(
            "expiration_chain_query_failure", "reauth", detail="reauth_needed"
        )
        raise
    except ConnectivityError:
        auth_event(
            "expiration_chain_query_failure",
            "transient",
            detail="provider_unreachable",
        )
        raise
    except ValueError:
        auth_event(
            "expiration_chain_query_failure", "error", detail="provider_error"
        )
        raise

    if extended:
        result["provider"] = payload

    auth_event(
        "expiration_chain_query_success",
        result["outcome"],
        detail=result["detail"],
    )
    return result


def get_option_expiration_chain_tool(
    client: Any,
    symbol: str,
    dte_max: int | None = None,
    extended: bool = False,
) -> dict:
    """MCP tool wrapper around :func:`get_option_expiration_chain`.

    Converts validation errors (``ValueError``/``TypeError``) and the
    auth-taxonomy errors (:class:`ConnectivityError`,
    :class:`ReauthorizationRequiredError`) into the MCP SDK's ``ToolError``
    so that the actionable message — not a generic wrapper — reaches the
    agent (bug domain-errors-swallowed; pattern:
    ``get_option_chain_tool``).
    """
    from schwab_mcp.errors import AuthError
    from schwab_mcp.tool_errors import raise_classified_tool_error

    try:
        return get_option_expiration_chain(
            client,
            symbol,
            dte_max=dte_max,
            extended=extended,
        )
    except (AuthError, ValueError, TypeError) as exc:
        raise_classified_tool_error(exc)
