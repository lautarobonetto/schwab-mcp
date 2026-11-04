"""Shared symbol grammar — the package's single source of truth.

One definition of "valid instrument symbol" for every domain that
validates a symbol string (bug ``duplicate-symbol-validation``):
``quotes`` (``get_quotes``), ``price_history`` (``get_price_history``)
and the option tools (``OptionChainQuery.validate()``).  The grammars
were first pinned by feature 010 (real-time quotes, research D5); the
live-evidence notes below are preserved from their original home in
``schwab_mcp.quotes``.

Grammar summary (normalized uppercase):

- Index: ``$`` + ``[A-Z0-9]{1,5}`` (``$SPX``).
- Option contract: root (≤ 6 chars, ``.`` allowed) + optional separator
  (`` ````/``_``) + ``YYMMDD`` + ``C``/``P`` + strike (literal, or
  8-digit OCC-encoded).
- Equity/ETF: ``[A-Z0-9.]{1,6}`` with at most one embedded ``.``
  (``AAPL``, ``BRK.B``).

The strict 15-character OCC tail grammar (``YYMMDD`` + ``C/P`` +
8-digit strike×1000) also lives here: :func:`parse_occ_symbol` is its
single source of truth, consumed by ``transactions._option_root`` and
``positions._parse_occ_option_symbol`` (TD-019).  No other module may
re-encode the tail grammar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INDEX_RE = re.compile(r"^\$[A-Z0-9]{1,5}$")
EQUITY_RE = re.compile(r"^[A-Z0-9.]{1,6}$")
# Root + optional separator(s) + OCC tail.  Strike: exactly 8 digits is
# the OCC-encoded form (strike x 1000); otherwise it is a literal strike
# (optional decimals).  The canonical OCC spacing (root padded to six
# columns) is matched by the separator run and rebuilt below.
OPTION_RE = re.compile(
    r"^(?P<root>[A-Z0-9.]{1,6})[ _]*"
    r"(?P<date>\d{6})(?P<cp>[CP])(?P<strike>\d+(?:\.\d+)?)$"
)


def canonical_option_symbol(root: str, date: str, cp: str, strike_raw: str) -> str | None:
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


OCC_TAIL_RE = re.compile(r"^\d{6}[CP]\d{8}$")
"""Strict OCC tail: ``YYMMDD`` + ``C/P`` + exactly 8 strike digits (×1000).

Unlike :data:`OPTION_RE` — whose strike group is deliberately permissive
(literal strikes like ``261120P63`` are valid for
:func:`classify_symbol`) — this matches only the canonical 15-character
provider tail, right-anchored regardless of root padding.
"""


@dataclass(frozen=True)
class OccSymbol:
    """Fields decoded from one OCC option symbol (:func:`parse_occ_symbol`).

    ``expiry`` is the ISO ``YYYY-MM-DD`` derivation of the tail's
    ``YYMMDD``; ``strike`` is the 8-digit tail field divided by 1000;
    ``root`` is the portion before the tail with padding stripped (empty
    for a bare 15-character symbol, preserving historical behavior).
    """

    root: str
    expiry: str
    put_call: str
    strike: float


def parse_occ_symbol(symbol: str | None) -> OccSymbol | None:
    """Parse one OCC option symbol — the tail grammar's single source of truth.

    The last 15 characters of an OCC option symbol always encode
    ``YYMMDD`` + ``C/P`` + 8-digit strike × 1000 (live evidence
    2026-10-24/27), regardless of how the root is padded.  Consolidates
    the grammar previously re-encoded by ``transactions._option_root`` and
    ``positions._parse_occ_option_symbol`` (TD-019); those helpers are now
    thin wrappers over this function.

    Returns ``None`` when the symbol is not a recognisable OCC option
    symbol (``None``/empty input, shorter than 15 characters, or a tail
    that fails :data:`OCC_TAIL_RE`).  No ``YYMMDD`` range validation is
    performed, matching the historical parsers' behavior.
    """
    if not symbol:
        return None
    tail = symbol[-15:]
    if len(tail) < 15 or not OCC_TAIL_RE.match(tail):
        return None
    yymmdd, put_call, strike_millis = tail[:6], tail[6], tail[7:]
    return OccSymbol(
        root=symbol[:-15].strip(),
        expiry=f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}",
        put_call=put_call,
        strike=int(strike_millis) / 1000.0,
    )


def classify_symbol(symbol: str) -> tuple[str, str] | None:
    """Classify one normalized symbol as ``(kind, provider_form)``.

    Returns ``None`` when the symbol matches no kind grammar (the caller
    reports ``malformed_symbol``).  Index symbols travel to the provider
    as requested; equity/ETF class shares (embedded dot) are rewritten
    to the provider's slash form (live probe 2026-11-02); option
    contracts are rewritten to the canonical OCC form above.  The
    caller is responsible for normalization (strip + uppercase) —
    :func:`classify_underlying` is the tolerant wrapper for callers
    that take raw agent input.
    """
    if INDEX_RE.match(symbol):
        return "index", symbol
    match = OPTION_RE.match(symbol)
    if match:
        provider = canonical_option_symbol(
            match.group("root"), match.group("date"), match.group("cp"),
            match.group("strike"),
        )
        if provider is not None:
            return "option", provider
        return None
    if EQUITY_RE.match(symbol) and symbol.count(".") <= 1:
        # Class shares (embedded dot) resolve at the provider ONLY in the
        # slash form (live probe 2026-11-02: ``BRK/B``/``HEI/A``/``BF/B``/
        # ``LEN/B`` -> candles + quotes; the dotted form -> not_found /
        # empty candles).  The agent-facing echo stays the dotted request
        # form; this translation is provider-internal.
        return "equity", symbol.replace(".", "/")
    return None


def classify_underlying(symbol: str) -> tuple[str, str] | None:
    """Classify a *raw* underlying symbol (option chain / expirations).

    The chain endpoints serve underlyings and pass ``symbol`` to the
    provider as-is, so this wrapper tolerates the two spellings agents
    actually send that :func:`classify_symbol` (a normalized-input
    contract) would reject: the provider-internal slash form (``BRK/B``
    — the provider resolves it, live probe 2026-11-02) and lowercase
    input (case is the provider's job on this path).  Slash → dot and
    uppercase normalization happen before classification; ``None``
    means the symbol matches no grammar and the caller must reject it
    before any upcall.
    """
    return classify_symbol(symbol.replace("/", ".").upper())