"""Real-time quotes with curated compact output (feature 010).

Implements the ``get_quotes`` domain: validated multi-symbol request
(equity/ETF, index, and option-contract symbol kinds), provider fetch
through the shared unwrapping/retry plumbing, curated per-symbol quotes
with explicit freshness (``data_state``) and the ok / quote_unavailable /
validation_error / provider_unreachable / reauth_needed result states.

Design sources: specs/010-real-time-quotes/{spec.md,data-model.md,
research.md,contracts/mcp-tools.md}.  Live provider evidence (captured
2026-10-27) is pinned by ``tests/unit/fixtures/quotes_payloads.py``; the
deviations it forced on research D2/D3/D4/D6 are recorded in the
implementing commit message.
"""

from __future__ import annotations

import re
from typing import Any

from schwab_mcp.errors import ConnectivityError, ReauthorizationRequiredError
from schwab_mcp.log import auth_event
from schwab_mcp.provider import response_json, trade_time_value
from schwab_mcp.tokens import retry_call


# =============================================================================
# Constants (contracts/mcp-tools.md §1-§2, research D5/D6)
# =============================================================================

MAX_SYMBOLS = 20
"""Distinct instrument limit per invocation (spec assumption, FR-007)."""

MAX_DESCRIPTION_LENGTH = 80
"""Provider descriptions are truncated to 80 chars (research D6)."""

QUOTE_FIELDS: tuple[str, ...] = (
    "symbol",
    "description",
    "last",
    "bid",
    "ask",
    "volume",
    "net_change",
    "net_change_pct",
    "data_state",
    "trade_time",
)
"""Fixed field order of each curated quote (data-model.md Quote)."""

MARKET = "equity"
"""The one market-hours session consulted per invocation (research D4):
equities/ETFs, option contracts, and index symbols all trade on the same
regular schedule."""

_INDEX_RE = re.compile(r"^\$[A-Z0-9]{1,5}$")
_EQUITY_RE = re.compile(r"^[A-Z0-9.]{1,6}$")
# Root + optional separator(s) + OCC tail.  Strike: exactly 8 digits is
# the OCC-encoded form (strike x 1000); otherwise it is a literal strike
# (optional decimals).  The canonical OCC spacing (root padded to six
# columns) is matched by the separator run and rebuilt below.
_OPTION_RE = re.compile(
    r"^(?P<root>[A-Z0-9.]{1,6})[ _]*"
    r"(?P<date>\d{6})(?P<cp>[CP])(?P<strike>\d+(?:\.\d+)?)$"
)


# =============================================================================
# Symbol normalization (research D5, FR-005/FR-013)
# =============================================================================


def _canonical_option_symbol(root: str, date: str, cp: str, strike_raw: str) -> str | None:
    """Build the canonical OCC provider form, or ``None`` if unencodable.

    Live evidence (2026-10-27): the provider quotes option contracts by
    canonical OCC form only — root left-padded to six columns plus a
    15-character tail ``YYMMDD`` + ``C``/``P`` + 8-digit strike x 1000.
    Exactly-8-digit strike fields are read as OCC-encoded; anything else
    is a literal strike price (the contract's compact grammar).
    """
    if "." not in strike_raw and len(strike_raw) == 8:
        strike = int(strike_raw) / 1000
    else:
        strike = float(strike_raw)
    encoded = round(strike * 1000)
    if strike <= 0 or encoded >= 100_000_000:
        return None
    return f"{root:<6}{date}{cp}{encoded:08d}"


def _classify(symbol: str) -> tuple[str, str] | None:
    """Classify one normalized symbol as ``(kind, provider_form)``.

    Returns ``None`` when the symbol matches no kind grammar (the caller
    reports ``malformed_symbol``).  Index and equity/ETF symbols travel
    to the provider as requested; option contracts are rewritten to the
    canonical OCC form above.
    """
    if _INDEX_RE.match(symbol):
        return "index", symbol
    match = _OPTION_RE.match(symbol)
    if match:
        provider = _canonical_option_symbol(
            match.group("root"), match.group("date"), match.group("cp"),
            match.group("strike"),
        )
        if provider is not None:
            return "option", provider
        return None
    if _EQUITY_RE.match(symbol) and symbol.count(".") <= 1:
        return "equity", symbol
    return None



# =============================================================================
# Result envelopes (contracts/mcp-tools.md §2-§3, FR-006/FR-008)
# =============================================================================


def _validation_error(detail: str, **extra: Any) -> dict:
    return {
        "outcome": "validation_error",
        "detail": detail,
        "retryable": False,
        **extra,
    }


def _provider_unreachable(detail: str = "provider_unreachable") -> dict:
    return {
        "outcome": "provider_unreachable",
        "detail": detail,
        "retryable": True,
    }


def _reauth_needed() -> dict:
    return {
        "outcome": "reauth_needed",
        "detail": "reauth_needed",
        "retryable": False,
    }


# =============================================================================
# Curated mapping (research D6 on the live payload shape)
# =============================================================================


def _description(entry: dict) -> str | None:
    """Provider description (``reference.description`` live), truncated
    to 80 chars; absent -> explicit ``None`` (FR-012)."""
    reference = entry.get("reference")
    raw = None
    if isinstance(reference, dict):
        raw = reference.get("description")
    if raw is None:
        raw = entry.get("description")
    if raw is None:
        return None
    return str(raw)[:MAX_DESCRIPTION_LENGTH]


def _data_state(entry: dict, market_open: bool) -> str:
    """Freshness ladder (research D4, live-evidence extension).

    Market closed -> ``closed`` (regardless of the quote signals).  Open:
    the provider's authoritative ``realtime`` flag or ``quoteType ==
    "Realtime"`` (D4) -> ``realtime``; anything else -> ``delayed``
    (conservative: never claim live when uncertain).
    """
    if not market_open:
        return "closed"
    if entry.get("realtime") is True:
        return "realtime"
    if entry.get("quoteType") == "Realtime":
        return "realtime"
    return "delayed"


def _curate_entry(display: str, kind: str, entry: dict, market_open: bool) -> dict:
    """Map one provider quote entry to the curated schema (data-model).

    Rounding: 2 decimals for equity/ETF/index symbols, 4 decimals for
    option-contract symbols (kind of the REQUESTED symbol).  Missing
    provider fields become explicit ``None`` (FR-012) — never invented.
    """
    quote = entry.get("quote")
    if not isinstance(quote, dict):
        quote = {}
    decimals = 4 if kind == "option" else 2

    def price(key: str) -> float | None:
        raw = quote.get(key)
        return None if raw is None else round(float(raw), decimals)

    volume = quote.get("totalVolume")
    if isinstance(volume, float) and volume.is_integer():
        volume = int(volume)

    net_change_raw = quote.get("netChange")
    close_raw = quote.get("closePrice")
    net_change_pct = None
    if net_change_raw is not None and close_raw not in (None, 0):
        net_change_pct = round(float(net_change_raw) / float(close_raw) * 100, 2)

    return {
        "symbol": display,
        "description": _description(entry),
        "last": price("lastPrice"),
        "bid": price("bidPrice"),
        "ask": price("askPrice"),
        "volume": volume,
        "net_change": price("netChange"),
        "net_change_pct": net_change_pct,
        "data_state": _data_state(entry, market_open),
        "trade_time": trade_time_value(quote.get("tradeTime")),
    }


# =============================================================================
# Provider fetch (research D4/D1/D2)
# =============================================================================


def _market_open(client: Any) -> bool:
    """Whether the shared regular session is open — one call per invocation.

    Reads the authoritative ``isOpen`` indicator of
    ``market_hours([equity])`` (live evidence).  A failure or a payload
    without the indicator raises :class:`ConnectivityError`: freshness is
    deterministic or absent, never guessed (research D4).
    """
    response = retry_call(client.market_hours, 0, [MARKET])
    payload = retry_call(response_json, 0, response=response)
    markets = payload.get("equity") if isinstance(payload, dict) else None
    if isinstance(markets, dict):
        for entry in markets.values():
            if isinstance(entry, dict) and "isOpen" in entry:
                return bool(entry["isOpen"])
    raise ConnectivityError(
        detail="market hours response carried no isOpen indicator"
    )


# =============================================================================
# Orchestration: get_quotes
# =============================================================================


def get_quotes(
    client: Any,
    symbols: str | list[str],
    extended: bool = False,
) -> dict:
    """Fetch curated quotes for 1..20 distinct *symbols* in one invocation.

    One ``quotes()`` call plus one ``market_hours`` call per invocation
    (research D1/D4) — never per symbol.  Validation runs before any
    upcall (FR-005/FR-007/FR-013).  No partial data (FR-006): any symbol
    the source cannot quote turns the whole invocation into a structured
    ``quote_unavailable`` error with per-symbol attribution.

    ``symbols`` may be a single string (one-symbol convenience) or a list
    of strings.  ``extended=True`` switches the provider call to
    ``fields="all"`` and adds the complete raw payload under
    ``"provider"`` (research D2).
    """
    auth_event("quotes_query_start", "initiated", detail="starting")

    # ------------------------------------------------------------------
    # 1. Tool-boundary types (D7: the wrapper converts these to ToolError)
    # ------------------------------------------------------------------
    if isinstance(symbols, str):
        raw_entries = [symbols]
    elif isinstance(symbols, list):
        raw_entries = list(symbols)
    else:
        auth_event("quotes_query_failure", "validation", detail="invalid_request")
        raise TypeError(
            "symbols must be a string or a list of strings "
            "(contract §1: 'string | list[string]'); "
            f"got {type(symbols).__name__}"
        )
    if any(not isinstance(entry, str) for entry in raw_entries):
        auth_event("quotes_query_failure", "validation", detail="invalid_request")
        raise TypeError(
            "every symbol must be a string (contract §1: 'string | list[string]')"
        )

    # ------------------------------------------------------------------
    # 2. Normalization + validation before any upcall (FR-005/FR-007/FR-013)
    # ------------------------------------------------------------------
    normalized = [entry.strip().upper() for entry in raw_entries if entry.strip()]
    if not normalized:
        auth_event(
            "quotes_query_failure", "validation", detail="empty_symbol_list"
        )
        return _validation_error("empty_symbol_list")

    errors: dict[str, str] = {}
    symbols_out: list[str] = []
    provider_forms: list[str] = []
    kinds: dict[str, str] = {}
    seen: set[str] = set()
    for symbol in normalized:
        classified = _classify(symbol)
        if classified is None:
            errors[symbol] = "malformed_symbol"
            continue
        kind, provider = classified
        if provider in seen:
            continue  # de-duplicate on instrument identity (canonical form)
        seen.add(provider)
        symbols_out.append(symbol)
        provider_forms.append(provider)
        kinds[symbol] = kind

    if errors:
        auth_event(
            "quotes_query_failure", "validation", detail="malformed_symbol"
        )
        return _validation_error("malformed_symbol", errors=errors)

    if len(symbols_out) > MAX_SYMBOLS:
        auth_event(
            "quotes_query_failure", "validation", detail="too_many_symbols"
        )
        return _validation_error(
            "too_many_symbols",
            limit=MAX_SYMBOLS,
            requested_count=len(symbols_out),
        )

    # ------------------------------------------------------------------
    # 3. Provider fetch (one market-hours + one quotes call, research D4)
    # ------------------------------------------------------------------
    fields = "all" if extended else "quote"
    try:
        market_open = _market_open(client)
        response = retry_call(
            client.quotes, 0, provider_forms, fields=fields, indicative=False
        )
        payload = retry_call(response_json, 0, response=response)
    except ConnectivityError as exc:
        cause = exc.__cause__
        if isinstance(cause, (ReauthorizationRequiredError, PermissionError)):
            auth_event("quotes_query_failure", "reauth", detail="reauth_needed")
            return _reauth_needed()
        auth_event(
            "quotes_query_failure",
            "provider_unreachable",
            detail="provider_unreachable",
        )
        return _provider_unreachable()

    # ------------------------------------------------------------------
    # 4. Missing-symbol detection (research D3: requested minus response
    #    keys) — no partial data (FR-006)
    # ------------------------------------------------------------------
    if not isinstance(payload, dict):
        payload = {}
    missing = [
        display
        for display, provider in zip(symbols_out, provider_forms)
        if provider not in payload
    ]
    if missing:
        auth_event("quotes_query_failure", "error", detail="quote_unavailable")
        return {
            "outcome": "quote_unavailable",
            "detail": "source_could_not_quote_all_symbols",
            "requested_count": len(symbols_out),
            "errors": {display: "not_found" for display in missing},
            "retryable": False,
        }

    # ------------------------------------------------------------------
    # 5. Curated envelope (contract §2)
    # ------------------------------------------------------------------
    quotes = {
        display: _curate_entry(display, kinds[display], payload[provider], market_open)
        for display, provider in zip(symbols_out, provider_forms)
    }
    result = {
        "outcome": "ok",
        "detail": "quotes_retrieved",
        "requested_count": len(symbols_out),
        "extended": bool(extended),
        "quote_fields": list(QUOTE_FIELDS),
        "quotes": quotes,
    }
    if extended:
        result["provider"] = payload
    return result


# =============================================================================
# MCP tool entry point (actionable errors for the MCP client)
# =============================================================================


def get_quotes_tool(
    client: Any,
    symbols: str | list[str],
    extended: bool = False,
) -> dict:
    """MCP tool wrapper around :func:`get_quotes`.

    Converts tool-boundary type errors (``ValueError``/``TypeError``)
    into the MCP SDK's ``ToolError`` so the actionable message reaches
    the agent (pattern: ``options_chain.get_option_chain_tool``).  All
    expected failures return structured result envelopes and pass
    through unchanged.
    """
    from mcp.server.mcpserver.exceptions import ToolError

    try:
        return get_quotes(client, symbols, extended=extended)
    except (ValueError, TypeError) as exc:
        raise ToolError(str(exc)) from exc
