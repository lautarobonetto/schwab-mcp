"""Failing unit tests for the delta-window selection (TDD red-phase).

Tests for ``build_chain_result(payload, query)`` when ``delta_target`` is set
(FR-004, data-model §3, research R2): per expiration AND per included type,
the anchor is the contract whose ``delta`` minimizes
``abs(abs(delta) - delta_target)`` among that type's contracts with a
non-null ``delta`` (ties → lower strike); the window is the anchor's index in
that type's ascending-strike sequence ± ``DELTA_WINDOW_SIDE`` (= 2) contiguous
strikes each side → up to 5 rows for that type, clipped to what exists (never
invented strikes).  With ``option_type="both"`` the CALL and PUT windows are
computed INDEPENDENTLY (clarification 2026-10-23); a strike row appears when
at least one included type selected the strike and each leg key is present
only if that type selected the strike.  ``max_strikes`` does NOT reduce the
delta window.

The delta window is not implemented yet (selection falls back to the ATM
strike window), so every test here fails (Red).

References
----------
- tmp/008-api-brief.md: binding API contract ("With ``delta_target``" bullet,
  StrikeRow leg semantics)
- specs/008-extract-option-chain/spec.md: FR-004
- specs/008-extract-option-chain/data-model.md: §3 deterministic selection
- specs/008-extract-option-chain/research.md: R2
- specs/008-extract-option-chain/quickstart.md: S2
"""

from __future__ import annotations

from datetime import date

import pytest

from tests.unit.helpers import (
    build_chain_payload,
    build_expiration_map,
    chain_expiry_date,
)


# =============================================================================
# Shared fixtures/helpers (lazy imports inside test bodies — house style)
# =============================================================================

_TODAY = date(2026, 10, 24)

# Nine-strike ladder, ascending.
_LADDER9: list[float] = [100.0 + 10.0 * i for i in range(9)]  # 100.0 .. 180.0

# CALL deltas strictly decreasing in strike; |delta| = 0.20 sits at index 4
# (strike 140.0) so the anchor has 2 strikes on each side of the ladder.
_CALL_DELTAS_CENTERED: list[float] = [
    0.60, 0.50, 0.40, 0.30, 0.20, 0.10, 0.05, 0.02, 0.01,
]

# PUT deltas strictly decreasing (more negative at low strikes — realistic
# shape); |delta| = 0.20 sits at index 6 (strike 160.0).
_PUT_DELTAS_LATE: list[float] = [
    -0.80, -0.70, -0.60, -0.50, -0.40, -0.30, -0.20, -0.10, -0.05,
]


def _query(**kwargs):
    """Build an ``OptionChainQuery`` with test-friendly defaults."""
    from schwab_mcp.options_chain import OptionChainQuery

    return OptionChainQuery(symbol="TEST", **kwargs)


def _chain(payload: dict, **query_kwargs) -> dict:
    """Run ``build_chain_result`` against *payload* with a pinned ``today``."""
    from schwab_mcp.options_chain import build_chain_result

    return build_chain_result(payload, _query(**query_kwargs), today=_TODAY)


def _exp(days_ahead: int) -> str:
    """ISO expiration date *days_ahead* calendar days after ``_TODAY``."""
    return chain_expiry_date(days_ahead, today=_TODAY)


def _rows(result: dict, expiration_index: int = 0) -> list[dict]:
    """Strike rows of the *expiration_index*-th expiration (sorted ascending)."""
    return result["expirations"][expiration_index]["strikes"]


def _strikes(result: dict, expiration_index: int = 0) -> list[float]:
    """Strike values of the *expiration_index*-th expiration, in order."""
    return [row["strike"] for row in _rows(result, expiration_index)]


def _strikes_with_leg(
    result: dict, leg: str, expiration_index: int = 0
) -> list[float]:
    """Strikes whose row carries the ``call``/``put`` *leg* key."""
    return [
        row["strike"] for row in _rows(result, expiration_index) if leg in row
    ]


def _delta_col() -> int:
    """Column position of ``delta`` in the fixed ``CONTRACT_FIELDS`` order."""
    from schwab_mcp.options_chain import CONTRACT_FIELDS

    return CONTRACT_FIELDS.index("delta")


def _leg_delta(leg: list) -> float | None:
    """The ``delta`` column of a serialized leg (short arrays are trailing-None)."""
    idx = _delta_col()
    return leg[idx] if idx < len(leg) else None


def _contract_at(contracts: dict, strike: float) -> dict:
    """The provider contract of one ``*ExpDateMap`` entry at *strike*.

    *contracts* is the per-expiration mapping ``{key: contract}`` (i.e.
    ``payload["callExpDateMap"][exp]``).
    """
    for contract in contracts.values():
        if contract["strikePrice"] == float(strike):
            return contract
    raise AssertionError(f"no contract at strike {strike}")


def _both_payload(
    strikes: list[float],
    call_deltas: list[float],
    put_deltas: list[float],
    *,
    days_ahead: int = 7,
) -> dict:
    """Payload whose CALL and PUT maps share one expiration and *strikes*."""
    exp = _exp(days_ahead)
    calls = build_expiration_map(exp, "CALL", strikes, deltas=call_deltas)
    puts = build_expiration_map(exp, "PUT", strikes, deltas=put_deltas)
    return build_chain_payload(calls, puts)


# =============================================================================
# Test class: anchor + 2 contiguous strikes each side (per expiration)
# =============================================================================


class TestDeltaWindow:
    """With ``delta_target``, per expiration: anchor = closest |delta| (ties →
    lower strike) + 2 contiguous strikes each side → up to 5, clipped to the
    existing ladder (never invented strikes)."""

    def test_center_plus_two_each_side_selects_exactly_five_strikes(self) -> None:
        """A centered anchor yields exactly the 5 strikes at indices ``i-2 ..
        i+2`` of the type's ascending-strike sequence (FR-004)."""
        payload = _both_payload(
            _LADDER9,
            _CALL_DELTAS_CENTERED,
            _PUT_DELTAS_LATE,
        )

        result = _chain(payload, option_type="calls", delta_target=0.20)

        assert result["outcome"] == "ok"
        # |0.20| is at index 4 (strike 140.0) → indices 2..6.
        assert _strikes(result) == [120.0, 130.0, 140.0, 150.0, 160.0]
        for row in _rows(result):
            assert "call" in row
            assert "put" not in row

    def test_window_clipped_at_lowest_anchor_invents_nothing(self) -> None:
        """Anchored at the lowest strike of the ladder the window is clipped:
        only the available strikes appear, nothing below the fixture ladder."""
        strikes = [100.0, 110.0, 120.0, 130.0, 140.0]
        # |delta| closest to 0.20 is exactly 0.20 at the LOWEST strike.
        call_deltas = [0.20, 0.15, 0.10, 0.05, 0.01]
        payload = _both_payload(strikes, call_deltas, _PUT_DELTAS_LATE)

        result = _chain(payload, option_type="calls", delta_target=0.20)

        # Anchor index 0 → indices 0..2 only; no strikes outside the ladder.
        assert _strikes(result) == [100.0, 110.0, 120.0]
        assert set(_strikes(result)) <= set(strikes)

    def test_window_clipped_at_highest_anchor(self) -> None:
        """Anchored at the highest strike the window keeps only the strikes
        that exist at and below it."""
        strikes = [100.0, 110.0, 120.0, 130.0, 140.0]
        # |delta| closest to 0.20 is exactly 0.20 at the HIGHEST strike.
        call_deltas = [0.60, 0.50, 0.40, 0.30, 0.20]
        payload = _both_payload(strikes, call_deltas, _PUT_DELTAS_LATE)

        result = _chain(payload, option_type="calls", delta_target=0.20)

        # Anchor index 4 → indices 2..4 only.
        assert _strikes(result) == [120.0, 130.0, 140.0]

    def test_fewer_than_five_strikes_returns_all_available(self) -> None:
        """A 3-strike ladder yields all 3 rows around the anchor (data-model
        §3: 'up to 5 (or the available ones around)').  ``max_strikes=1`` makes
        the ATM fallback keep only 2 strikes — the delta window keeps all 3."""
        strikes = [100.0, 110.0, 120.0]
        call_deltas = [0.35, 0.20, 0.05]
        payload = _both_payload(strikes, call_deltas, _PUT_DELTAS_LATE)

        result = _chain(
            payload,
            option_type="calls",
            delta_target=0.20,
            max_strikes=1,
        )

        assert _strikes(result) == [100.0, 110.0, 120.0]

    def test_null_delta_contract_is_never_anchor_but_may_be_neighbor(self) -> None:
        """A contract with ``delta=None`` is excluded from anchor selection yet
        still appears inside the window as a neighbor — its leg shows ``None``
        in the delta column (FR-007), never an invented value."""
        strikes = [100.0, 110.0, 120.0, 130.0, 140.0]
        call_deltas = [0.55, 0.50, 0.30, 0.45, 0.40]
        payload = _both_payload(strikes, call_deltas, _PUT_DELTAS_LATE)
        exp = _exp(7)
        # Simulate a missing delta on the MIDDLE strike (FR-007).
        _contract_at(payload["callExpDateMap"][exp], 120.0)["delta"] = None

        result = _chain(payload, option_type="calls", delta_target=0.20)

        # Distances to 0.20 over the non-null deltas: 0.35, 0.30, -, 0.25, 0.20
        # → anchor is strike 140.0 (index 4) → indices 2..4.  If the null-delta
        # contract were anchor-eligible (e.g. as 0.0) it would tie at distance
        # 0.20 and win on the lower-strike tie-break, expanding the window to
        # all five strikes — the exact 3-strike window pins the exclusion.
        assert _strikes(result) == [120.0, 130.0, 140.0]

        # The null-delta contract appears as a window NEIGHBOR with delta=None.
        neighbor = next(r for r in _rows(result) if r["strike"] == 120.0)
        assert "call" in neighbor
        assert _leg_delta(neighbor["call"]) is None

    def test_window_computed_independently_per_expiration(self) -> None:
        """Each expiration gets its own anchor and window from its own deltas."""
        strikes = _LADDER9
        exp1, exp2 = _exp(7), _exp(21)
        calls1 = build_expiration_map(
            exp1, "CALL", strikes, deltas=_CALL_DELTAS_CENTERED
        )
        # |delta| = 0.20 at index 7 (strike 170.0) → indices 5..8 (clipped).
        calls2 = build_expiration_map(
            exp2, "CALL", strikes, deltas=[0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10]
        )
        puts = build_expiration_map(exp1, "PUT", strikes, deltas=_PUT_DELTAS_LATE)
        payload = build_chain_payload({**calls1, **calls2}, puts)

        result = _chain(payload, option_type="calls", delta_target=0.20)

        assert [e["expiration_date"] for e in result["expirations"]] == [exp1, exp2]
        assert _strikes(result, 0) == [120.0, 130.0, 140.0, 150.0, 160.0]
        assert _strikes(result, 1) == [150.0, 160.0, 170.0, 180.0]


# =============================================================================
# Test class: per-type independent windows (option_type="both", clarif. 2026-10-23)
# =============================================================================


class TestDeltaPerTypeWindows:
    """With ``option_type="both"`` the CALL and PUT delta windows are computed
    INDEPENDENTLY per expiration; leg keys appear only where the type's own
    window selected the strike."""

    def test_both_selects_independent_windows_per_type(self) -> None:
        """CALL and PUT anchors sit at different strikes → disjoint-offset
        windows; the row union covers up to 7 strikes here (2 × 5 − overlap)."""
        payload = _both_payload(
            _LADDER9, _CALL_DELTAS_CENTERED, _PUT_DELTAS_LATE
        )

        result = _chain(payload, option_type="both", delta_target=0.20)

        # CALL anchor: |0.20| at index 4 (strike 140.0) → strikes 120..160.
        assert _strikes_with_leg(result, "call") == [
            120.0, 130.0, 140.0, 150.0, 160.0,
        ]
        # PUT anchor: |0.20| at index 6 (strike 160.0) → strikes 140..180.
        assert _strikes_with_leg(result, "put") == [
            140.0, 150.0, 160.0, 170.0, 180.0,
        ]
        # A row appears when at least one type selected the strike (union).
        assert _strikes(result) == [
            120.0, 130.0, 140.0, 150.0, 160.0, 170.0, 180.0,
        ]

    def test_leg_key_present_only_for_type_that_selected_the_strike(self) -> None:
        """Strikes selected by only one type carry that leg key alone."""
        payload = _both_payload(
            _LADDER9, _CALL_DELTAS_CENTERED, _PUT_DELTAS_LATE
        )

        result = _chain(payload, option_type="both", delta_target=0.20)

        rows = {row["strike"]: row for row in _rows(result)}
        # CALL-only window edges: no PUT leg outside the PUT window.
        for strike in (120.0, 130.0):
            assert "call" in rows[strike]
            assert "put" not in rows[strike]
        # PUT-only window edges: no CALL leg outside the CALL window.
        for strike in (170.0, 180.0):
            assert "put" in rows[strike]
            assert "call" not in rows[strike]
        # Overlap: both legs.
        for strike in (140.0, 150.0, 160.0):
            assert "call" in rows[strike]
            assert "put" in rows[strike]

    def test_puts_only_rows_carry_put_legs_only(self) -> None:
        """``option_type="puts"`` + ``delta_target=0.20``: only ``put`` legs
        (even though CALL data is present in the payload), ≤ 5 strikes
        (quickstart S2)."""
        payload = _both_payload(
            _LADDER9, _CALL_DELTAS_CENTERED, _PUT_DELTAS_LATE
        )

        result = _chain(payload, option_type="puts", delta_target=0.20)

        # PUT anchor: |(-0.20)| at index 6 (strike 160.0) → indices 4..8.
        assert _strikes(result) == [140.0, 150.0, 160.0, 170.0, 180.0]
        assert len(_rows(result)) <= 5
        for row in _rows(result):
            assert "put" in row
            assert "call" not in row


# =============================================================================
# Test class: edges (max_strikes independence, ties, filters echo)
# =============================================================================


class TestDeltaEdges:
    """``max_strikes`` never shrinks the delta window; anchor ties resolve to
    the lower strike; the ok response echoes ``filters["delta_target"]``."""

    @pytest.mark.parametrize("max_strikes", [1, 2])
    def test_max_strikes_does_not_reduce_delta_window(self, max_strikes: int) -> None:
        """Even ``max_strikes=1``/``2`` keeps 5 strikes per type — the delta
        window does not interact with ``max_strikes`` (data-model §3,
        clarification 2026-10-23)."""
        payload = _both_payload(
            _LADDER9, _CALL_DELTAS_CENTERED, _PUT_DELTAS_LATE
        )

        result = _chain(
            payload,
            option_type="both",
            delta_target=0.20,
            max_strikes=max_strikes,
        )

        assert _strikes_with_leg(result, "call") == [
            120.0, 130.0, 140.0, 150.0, 160.0,
        ]
        assert _strikes_with_leg(result, "put") == [
            140.0, 150.0, 160.0, 170.0, 180.0,
        ]

    def test_anchor_tie_prefers_lower_strike(self) -> None:
        """When two contracts are equidistant from the target the anchor is the
        one at the LOWER strike."""
        strikes = [100.0, 110.0, 120.0, 130.0, 140.0]
        # Distances to 0.20: 0.10, 0.10, 0.15, 0.18, 0.19 — tie at 100/110.
        call_deltas = [0.30, 0.10, 0.05, 0.02, 0.01]
        payload = _both_payload(strikes, call_deltas, _PUT_DELTAS_LATE)

        result = _chain(payload, option_type="calls", delta_target=0.20)

        # Anchor = strike 100.0 (index 0) → indices 0..2.  A higher-strike
        # anchor (110.0) would give indices 0..3 — 4 rows instead of 3.
        assert _strikes(result) == [100.0, 110.0, 120.0]

    def test_filters_echo_delta_target(self) -> None:
        """The ok response echoes the effective filters, including
        ``delta_target``."""
        payload = _both_payload(
            _LADDER9, _CALL_DELTAS_CENTERED, _PUT_DELTAS_LATE
        )

        result = _chain(payload, option_type="calls", delta_target=0.20)

        assert result["outcome"] == "ok"
        assert result["filters"]["delta_target"] == 0.20
