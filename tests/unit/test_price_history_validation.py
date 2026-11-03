"""RED-phase input-validation tests for ``get_price_history`` (T004 + T013).

TDD red-phase: ``schwab_mcp.price_history`` exposes the skeleton only
(``NotImplementedError``), so every test here fails until T009/T012 land.

Pins (research D9 + contracts/mcp-tools.md §1/§3, data-model.md preset
matrix, quickstart S5, FR-002/FR-003/FR-007/FR-018):

T004 (US1) — symbol grammar and request validation:

- equity/ETF ``[A-Z0-9]{1,6}`` with at most one embedded ``.`` and index
  ``$[A-Z0-9]{1,5}`` accepted on the normalized (strip + uppercase) form;
- option-contract symbols rejected at validation as
  ``validation_error`` / ``unsupported_symbol_kind`` (D9) — both fixture
  spellings (compact and canonical OCC);
- symbols matching no grammar and missing symbols (``None`` / empty /
  blank) rejected as ``validation_error`` / ``malformed_symbol``;
- defaults ``daily`` / ``1m`` echoed as the effective selection when
  ``frequency``/``period`` are omitted (FR-002);
- frequency outside {``5m``, ``15m``, ``30m``, ``1h``, ``daily``,
  ``weekly``} rejected as ``unsupported_frequency``;
- fail-before-upcall (FR-007): every validation failure performs ZERO
  provider calls.

T013 (US2) — preset-table and applicability validation:

- every period outside the frequency's preset row of the data-model
  matrix rejected as ``validation_error`` / ``unsupported_period``, the
  error naming the valid presets (FR-018, clarification Q4);
- every (frequency, period) pair of the matrix accepted at the exact
  table boundary: exactly one ``price_history()`` call, ``ok`` envelope;
- ``extended_hours=true`` with ``daily``/``weekly`` rejected as
  ``validation_error`` / ``extended_hours_not_applicable`` (D4), zero
  provider calls.

Contract assumptions (recorded in the T004/T013 report): the shared
validation envelope mirrors ``quotes._validation_error`` exactly
(``outcome`` / ``detail`` / ``retryable`` plus extras, FR-009/C-02), and
``unsupported_period`` names its valid presets in a ``valid_presets``
extra field (compared as a set, order-free).  Wrong TYPES at the tool
boundary (non-string ``symbol``) raise ``TypeError``/``ValueError`` —
converted to ``ToolError`` by ``get_price_history_tool`` — while a
missing/``None``/empty symbol is an invalid VALUE and returns the
``malformed_symbol`` envelope (contract split of the quotes precedent).
"""

from __future__ import annotations

import pytest

from tests.unit.fixtures import price_history_payloads as fx
from tests.unit.helpers import FakePriceHistoryClient


# =============================================================================
# Normative preset matrix (data-model.md "Period presets × frequency matrix")
# =============================================================================

PRESET_MATRIX: dict[str, tuple[str, ...]] = {
    "5m": ("1d", "2d", "3d"),
    "15m": ("1d", "2d", "5d", "10d"),
    "30m": ("1d", "2d", "5d", "10d"),
    "1h": ("1d", "2d", "5d", "10d"),
    "daily": ("1m", "3m", "6m", "1y", "ytd"),
    "weekly": ("1m", "3m", "6m", "1y", "2y", "3y", "5y", "ytd"),
}

ALL_PRESETS: frozenset[str] = frozenset(
    preset for presets in PRESET_MATRIX.values() for preset in presets
)
"""Every named preset of the matrix (13 distinct names)."""

# Frequencies outside the declared set (FR-003).  None of these is a valid
# preset name either; frequency validation runs before the preset lookup.
BAD_FREQUENCIES = ["1m", "monthly", "hourly", "60m", "1min", "minute"]

# Symbols matching no kind grammar (D9): neither equity/ETF, nor index,
# nor an option contract (option shapes are covered separately).
MALFORMED = [
    ("BAD SYMBOL", "internal space, not option-shaped"),
    ("TOOLONGSYM", "equity longer than 6 characters"),
    ("BRK.B.A", "two embedded dots"),
    ("AAPL@", "illegal character"),
    ("$TOOLONG1", "index root longer than 5 characters"),
    ("$BAD$", "index with illegal characters"),
    ("$", "bare index prefix"),
]


def _client(symbol: str = fx.SYMBOL) -> FakePriceHistoryClient:
    """Fake provider serving a non-empty daily payload for *symbol*.

    A non-empty payload keeps a wrongly-passing validation observable:
    the test would see an ``ok`` envelope where ``validation_error`` is
    required.
    """
    return FakePriceHistoryClient(payload=fx.build_daily_payload(symbol=symbol))


# =============================================================================
# Accepted symbol kinds and normalization (FR-007, research D9)
# =============================================================================


class TestAcceptedSymbolKinds:
    """Equity/ETF and index symbols pass validation, reach exactly one
    provider call, and the response echoes the normalized symbol."""

    @pytest.mark.parametrize(
        "requested,expected",
        [
            (" spy ", "SPY"),
            ("AAPL", "AAPL"),
            ("NOK", "NOK"),
            ("BRK.B", "BRK.B"),
            ("$SPX", "$SPX"),
            ("$vix", "$VIX"),
        ],
        ids=[
            "stripped-lowercase",
            "equity",
            "short-equity",
            "class-shares",
            "index",
            "index-lowercase",
        ],
    )
    def test_accepted_symbol_echoed_normalized(self, requested, expected) -> None:
        """Every accepted spelling yields ``ok`` with the normalized echo."""
        from schwab_mcp.price_history import get_price_history

        client = _client(symbol=expected)
        result = get_price_history(client, requested)

        assert result["outcome"] == "ok", "equity/ETF and index grammars must be accepted"
        assert result["symbol"] == expected
        assert client.call_count == 1

    def test_normalization_strips_and_uppercases(self) -> None:
        """``" spy "`` is accepted and both the response and the upcall
        carry the normalized ``SPY`` (strip + uppercase)."""
        from schwab_mcp.price_history import get_price_history

        client = _client(symbol="SPY")
        result = get_price_history(client, " spy ")

        assert result["outcome"] == "ok"
        assert result["symbol"] == "SPY"
        assert client.price_history_calls[0]["symbol"] == "SPY"


# =============================================================================
# Option-contract symbols rejected (D9, quickstart S5 case 1)
# =============================================================================


class TestOptionSymbolsRejected:
    """Option-contract symbols are rejected at validation
    (``unsupported_symbol_kind``): the provider price-history endpoint
    serves underlyings, not option contracts.  Both the compact contract
    spelling and the canonical OCC spelling are rejected."""

    @pytest.mark.parametrize(
        "symbol",
        [fx.OPTION_SYMBOL, fx.OPTION_SYMBOL_CANONICAL],
        ids=["contract-spelling", "canonical-occ-spelling"],
    )
    def test_option_symbol_rejected_as_unsupported_kind(self, symbol) -> None:
        from schwab_mcp.price_history import get_price_history

        client = _client()
        result = get_price_history(client, symbol)

        assert result["outcome"] == "validation_error", symbol
        assert result["detail"] == "unsupported_symbol_kind"
        assert result["retryable"] is False
        assert client.call_count == 0
        assert client.price_history_calls == []


# =============================================================================
# Malformed symbols (D9: matches no grammar)
# =============================================================================


class TestMalformedSymbols:
    """A symbol matching no kind grammar -> ``validation_error`` /
    ``malformed_symbol``, zero upcalls."""

    @pytest.mark.parametrize(
        "symbol,case", MALFORMED, ids=[s.replace(" ", "-") for s, _ in MALFORMED]
    )
    def test_malformed_symbol_rejected(self, symbol, case) -> None:
        from schwab_mcp.price_history import get_price_history

        client = _client()
        result = get_price_history(client, symbol)

        assert result["outcome"] == "validation_error", case
        assert result["detail"] == "malformed_symbol"
        assert result["retryable"] is False
        assert client.call_count == 0, case
        assert client.price_history_calls == [], case


# =============================================================================
# Missing symbol (D9: missing -> malformed_symbol)
# =============================================================================


class TestMissingSymbol:
    """Missing symbol (``None`` or empty/blank string) is an invalid VALUE:
    ``validation_error`` / ``malformed_symbol`` before any upcall — never
    a tool-boundary ``TypeError``."""

    @pytest.mark.parametrize(
        "symbol", [None, "", "   "], ids=["none", "empty-string", "blank-string"]
    )
    def test_missing_symbol_returns_malformed_symbol(self, symbol) -> None:
        from schwab_mcp.price_history import get_price_history

        client = _client()
        result = get_price_history(client, symbol)

        assert result["outcome"] == "validation_error"
        assert result["detail"] == "malformed_symbol"
        assert result["retryable"] is False
        assert client.call_count == 0
        assert client.price_history_calls == []


# =============================================================================
# Defaults: effective selection echo (FR-002)
# =============================================================================


class TestDefaults:
    """Omitted ``frequency``/``period`` resolve to ``daily`` / ``1m`` and
    the successful response echoes the effective selection (contract §2)."""

    def test_default_frequency_and_period_echoed(self) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        result = get_price_history(client, fx.SYMBOL)

        assert result["outcome"] == "ok"
        assert result["detail"] == "price_history_retrieved"
        assert result["frequency"] == "daily", "FR-002 default frequency"
        assert result["period"] == "1m", "FR-002 default period"
        assert result["extended_hours"] is False
        assert result["extended"] is False
        assert client.call_count == 1


# =============================================================================
# Frequency validation (FR-003, research D9)
# =============================================================================


class TestFrequencyValidation:
    """Frequency outside {5m, 15m, 30m, 1h, daily, weekly} ->
    ``validation_error`` / ``unsupported_frequency``, zero upcalls."""

    @pytest.mark.parametrize("frequency", BAD_FREQUENCIES)
    def test_unsupported_frequency_rejected(self, frequency) -> None:
        from schwab_mcp.price_history import get_price_history

        client = _client()
        result = get_price_history(client, fx.SYMBOL, frequency=frequency)

        assert result["outcome"] == "validation_error", frequency
        assert result["detail"] == "unsupported_frequency"
        assert result["retryable"] is False
        assert client.call_count == 0
        assert client.price_history_calls == []


# =============================================================================
# Preset matrix accepted at the exact table boundary (T013, FR-018)
# =============================================================================

MATRIX_PAIRS = [
    (frequency, period)
    for frequency, presets in PRESET_MATRIX.items()
    for period in presets
]


class TestPresetMatrixAcceptance:
    """Every (frequency, period) pair of the data-model matrix passes
    validation and reaches exactly one provider call with an ``ok``
    envelope (pins acceptance at the exact boundary)."""

    @pytest.mark.parametrize(
        "frequency,period",
        MATRIX_PAIRS,
        ids=[f"{frequency}-{period}" for frequency, period in MATRIX_PAIRS],
    )
    def test_matrix_pair_accepted_with_one_upcall(self, frequency, period) -> None:
        from schwab_mcp.price_history import get_price_history

        client = _client()
        result = get_price_history(client, fx.SYMBOL, frequency=frequency, period=period)

        assert result["outcome"] == "ok", f"{frequency}/{period} is inside the matrix"
        assert result["frequency"] == frequency
        assert result["period"] == period
        assert client.call_count == 1, "exactly one price_history() call (research D1)"
        assert len(client.price_history_calls) == 1


# =============================================================================
# Period presets outside the frequency's row (T013, FR-018, clarification Q4)
# =============================================================================

# Every matrix preset that is NOT in the frequency's own row (cross-
# frequency violations) plus non-preset garbage spellings.
INVALID_PERIOD_PAIRS = [
    (frequency, period)
    for frequency, presets in PRESET_MATRIX.items()
    for period in sorted(ALL_PRESETS - set(presets))
] + [
    (frequency, period)
    for frequency in PRESET_MATRIX
    for period in ("10y", "1w", "abc")
]


class TestUnsupportedPeriod:
    """A period outside the frequency's preset row ->
    ``validation_error`` / ``unsupported_period`` naming the valid
    presets, zero upcalls (presets outside the table are validation
    errors, never truncations)."""

    @pytest.mark.parametrize(
        "frequency,period",
        INVALID_PERIOD_PAIRS,
        ids=[f"{frequency}-{period}" for frequency, period in INVALID_PERIOD_PAIRS],
    )
    def test_period_outside_row_rejected_naming_valid_presets(
        self, frequency, period
    ) -> None:
        from schwab_mcp.price_history import get_price_history

        client = _client()
        result = get_price_history(client, fx.SYMBOL, frequency=frequency, period=period)

        assert result["outcome"] == "validation_error", f"{frequency}/{period}"
        assert result["detail"] == "unsupported_period"
        assert result["retryable"] is False
        assert sorted(result["valid_presets"]) == sorted(PRESET_MATRIX[frequency]), (
            "the error must name the valid presets of the frequency's row "
            "(FR-018, clarification Q4)"
        )
        assert client.call_count == 0
        assert client.price_history_calls == []


# =============================================================================
# Extended-hours applicability (T013, research D4, clarification Q1)
# =============================================================================


class TestExtendedHoursApplicability:
    """``extended_hours=true`` is valid only for intraday frequencies;
    with ``daily``/``weekly`` it is a validation error before any upcall."""

    @pytest.mark.parametrize(
        "frequency,period",
        [("daily", "1m"), ("daily", "ytd"), ("weekly", "1m"), ("weekly", "5y")],
        ids=["daily-1m", "daily-ytd", "weekly-1m", "weekly-5y"],
    )
    def test_extended_hours_not_applicable_on_daily_weekly(
        self, frequency, period
    ) -> None:
        from schwab_mcp.price_history import get_price_history

        client = _client()
        result = get_price_history(
            client,
            fx.SYMBOL,
            frequency=frequency,
            period=period,
            extended_hours=True,
        )

        assert result["outcome"] == "validation_error", f"{frequency}/{period}"
        assert result["detail"] == "extended_hours_not_applicable"
        assert result["retryable"] is False
        assert client.call_count == 0
        assert client.price_history_calls == []

    def test_extended_hours_accepted_on_intraday(self) -> None:
        """``extended_hours=true`` with an intraday frequency is valid at
        the boundary (only daily/weekly reject it)."""
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(
            payload=fx.build_30m_payload(symbol="AAPL")
        )
        result = get_price_history(
            client, "AAPL", frequency="30m", period="5d", extended_hours=True
        )

        assert result["outcome"] == "ok"
        assert result["extended_hours"] is True
        assert client.call_count == 1


# =============================================================================
# Wrong input types (tool-boundary errors, quotes precedent)
# =============================================================================


class TestInputTypeError:
    """Wrong TYPES at the tool boundary (non-string ``symbol``) raise
    ``TypeError``/``ValueError`` — surfaced as MCP ``ToolError`` by the
    wrapper.  Invalid VALUES (``None`` / empty) are envelopes instead;
    see :class:`TestMissingSymbol`."""

    @pytest.mark.parametrize(
        "symbol", [42, ["SPY"], {"SPY": 1}, 3.5], ids=["int", "list", "dict", "float"]
    )
    def test_non_string_symbol_raises_type_error(self, symbol) -> None:
        from schwab_mcp.price_history import get_price_history

        with pytest.raises((TypeError, ValueError)):
            get_price_history(_client(), symbol)

    def test_tool_wrapper_converts_to_tool_error(self) -> None:
        """``get_price_history_tool`` converts the tool-boundary
        TypeError into the MCP ToolError (pattern: ``get_quotes_tool``)."""
        from mcp.server.mcpserver.exceptions import ToolError

        from schwab_mcp.price_history import get_price_history_tool

        with pytest.raises(ToolError):
            get_price_history_tool(_client(), 42)