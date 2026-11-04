"""Parity tests for the OCC option symbol parser (TD-019).

The 15-character OCC tail grammar (``YYMMDD`` + ``C/P`` + 8-digit
strike×1000) was encoded independently in three modules:
``schwab_mcp.symbols`` (SSOT, TD-009), ``schwab_mcp.transactions``
(``_option_root``) and ``schwab_mcp.positions``
(``_parse_occ_option_symbol``).  TD-019 consolidates the grammar into
``schwab_mcp.symbols.parse_occ_symbol``; these tests pin that the shared
parser reproduces every result of the existing private parsers, so the
consolidation cannot silently change behavior and future grammar changes
have exactly one place to land.

Every valid fixture is drawn from the already-pinned suites
(``test_transactions_underlying.py``, ``test_positions_live_response.py``).
"""

from __future__ import annotations

import pytest

from schwab_mcp.positions import _parse_occ_option_symbol
from schwab_mcp.symbols import parse_occ_symbol
from schwab_mcp.transactions import _option_root

# (symbol, root, expiry, put_call, strike)
VALID: list[tuple[str, str, str, str, float]] = [
    ("AMD   261120P00630000", "AMD", "2026-11-20", "P", 630.0),
    ("NOK261218P00011000", "NOK", "2026-12-18", "P", 11.0),
    ("A     261120C00100000", "A", "2026-11-20", "C", 100.0),
    ("SPXW  261218C05000000", "SPXW", "2026-12-18", "C", 5000.0),
    ("MSFT  261220P00250000", "MSFT", "2026-12-20", "P", 250.0),
    ("AMD  261120P00090000", "AMD", "2026-11-20", "P", 90.0),
    # Bare 15-char tail with no root at all: root is the empty string.
    ("261120C00100000", "", "2026-11-20", "C", 100.0),
]

# Every input the existing parsers reject; all three must agree on None.
INVALID = [
    "AAPL",  # equity, shorter than 15 chars
    "",  # empty
    "SHORT",  # shorter than 15 chars
    "NOK   261120X00630000",  # C/P position holds X
    "NOK   26112X000630000",  # non-digit in the date field
    "NOK   261218P0001100X",  # non-digit in the strike field
]


class TestParseOccSymbolShared:
    """The shared parser decodes root, ISO expiry, C/P and strike÷1000."""

    @pytest.mark.parametrize(("symbol", "root", "expiry", "put_call", "strike"), VALID)
    def test_parses_all_tail_fields(
        self,
        symbol: str,
        root: str,
        expiry: str,
        put_call: str,
        strike: float,
    ) -> None:
        parsed = parse_occ_symbol(symbol)
        assert parsed is not None
        assert parsed.root == root
        assert parsed.expiry == expiry
        assert parsed.put_call == put_call
        assert parsed.strike == strike

    @pytest.mark.parametrize("symbol", INVALID)
    def test_malformed_tail_returns_none(self, symbol: str) -> None:
        assert parse_occ_symbol(symbol) is None

    def test_none_input_returns_none(self) -> None:
        assert parse_occ_symbol(None) is None

    def test_literal_strike_tail_is_rejected(self) -> None:
        """The strict 15-char OCC tail only: a literal-strike symbol that
        ``OPTION_RE`` accepts (permissive, for ``classify_symbol``) is NOT
        a parseable OCC symbol here."""
        assert parse_occ_symbol("AMD   261120P63") is None


class TestParityWithOptionRoot:
    """``transactions._option_root`` agrees with the shared parser."""

    @pytest.mark.parametrize(("symbol", "root"), [(s, r) for s, r, *_ in VALID])
    def test_root_matches_shared_parser(self, symbol: str, root: str) -> None:
        assert _option_root(symbol) == root

    @pytest.mark.parametrize("symbol", INVALID)
    def test_invalid_tail_returns_none(self, symbol: str) -> None:
        assert _option_root(symbol) is None

    def test_none_input_returns_none(self) -> None:
        assert _option_root(None) is None


class TestParityWithPositionsParser:
    """``positions._parse_occ_option_symbol`` agrees with the shared parser."""

    @pytest.mark.parametrize(
        ("symbol", "expiry", "strike"), [(s, e, k) for s, _, e, _, k in VALID]
    )
    def test_strike_and_expiry_match_shared_parser(
        self, symbol: str, expiry: str, strike: float
    ) -> None:
        assert _parse_occ_option_symbol(symbol) == (strike, expiry)

    @pytest.mark.parametrize("symbol", INVALID)
    def test_invalid_tail_returns_none_pair(self, symbol: str) -> None:
        assert _parse_occ_option_symbol(symbol) == (None, None)