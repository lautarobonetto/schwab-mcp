"""End-to-end integration tests for ``get_option_chain`` with a provider double.

These are TDD red-phase tests: ``schwab_mcp.options_chain`` exposes
``ChainDataError`` but not ``get_option_chain`` yet, so every test fails with
``ImportError``. Once implemented, all tests should pass.

The suite runs WITHOUT network and WITHOUT a token: a ``FakeChainClient``
records every ``option_chains`` call and returns a canned payload wrapped in a
real ``requests.Response`` (``tests.unit.helpers.build_response``), exactly
like the ``schwabdev`` client does.

Covers (from tasks.md T009)
---------------------------
- ``ok`` chain (quickstart S1 shape)
- ``no_options_listed`` structured result
- ``no_expirations_in_range`` structured result
- FR-013: whole expiration missing -> ``ChainDataError``, never a partial chain
- ``extended=true`` adds the raw provider payload (contract §2)
- SC-004 / FR-011: one invocation returns the full chain, no pagination keys

References
----------
- tmp/008-api-brief.md (binding API contract: states, ``extended``,
  FR-013 ``ChainDataError`` rule, no-pagination guarantee)
- specs/008-extract-option-chain/contracts/mcp-tools.md (§2 output, §4 results)
- specs/008-extract-option-chain/spec.md (FR-009, FR-011, FR-013, SC-004)
"""

from __future__ import annotations

import pytest

from tests.unit.helpers import (
    build_chain_payload,
    build_expiration_map,
    build_response,
    chain_expiry_date,
)

# Forbidden response keys anywhere in the response (FR-011 / SC-004).
PAGINATION_KEYS = frozenset(
    {
        "cursor",
        "offset",
        "next_offset",
        "has_more",
        "nextCursor",
        "page",
        "returned",
    }
)

# The 23 curated columns in exact fixed order (data-model §1 / contract §2).
EXPECTED_CONTRACT_FIELDS = [
    "bid", "ask", "last", "mark", "mark_change", "mark_pct_change",
    "high", "low", "open", "close", "volume", "open_interest",
    "iv", "delta", "gamma", "theta", "vega", "rho",
    "theoretical_value", "time_value", "multiplier", "trade_time",
    "deliverable_note",
]

# Fixture strikes: 7 strikes around the 251.31 underlying price.
FIXTURE_STRIKES = [245.0, 248.0, 250.0, 251.0, 252.0, 255.0, 260.0]


# =============================================================================
# Provider double
# =============================================================================


class FakeChainClient:
    """Provider double recording ``option_chains`` calls (no network).

    Returns every payload wrapped in a real ``requests.Response`` via
    ``build_response``, mirroring the ``schwabdev`` client contract.
    """

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls: list[dict] = []

    def option_chains(self, symbol: str, **kwargs):
        self.calls.append({"symbol": symbol, **kwargs})
        return build_response(self._payload)


# =============================================================================
# Fixture builders
# =============================================================================


def _two_leg_payload(extra_days: int = 70) -> dict:
    """Chain payload with both leg maps at +7, +30 and +*extra_days* days.

    ``underlying_price=251.31`` (quickstart S1 shape).  With the default
    60-day cap, the +*extra_days* expiration is expected to be excluded when
    *extra_days* > 60.
    """
    call_map: dict = {}
    put_map: dict = {}
    for days in (7, 30, extra_days):
        expiration = chain_expiry_date(days)
        call_map.update(build_expiration_map(expiration, "CALL", FIXTURE_STRIKES))
        put_map.update(build_expiration_map(expiration, "PUT", FIXTURE_STRIKES))
    return build_chain_payload(call_map, put_map, underlying_price=251.31)


def _collect_keys(obj, found: set) -> set:
    """Recursively collect every dict key in a JSON-able structure."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            found.add(key)
            _collect_keys(value, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_keys(item, found)
    return found


# =============================================================================
# ok chain (quickstart S1 shape)
# =============================================================================


class TestOkChain:
    """Default ``get_option_chain(client, 'TEST')`` over a 3-expiration fixture.

    Asserts the ``ok`` state, the DTE cap, both legs per strike row, the
    curated column manifest, and the SC-004/FR-011 no-pagination guarantee.
    """

    def test_ok_outcome_and_detail(self) -> None:
        """A well-formed payload yields outcome 'ok' and detail 'chain_retrieved'."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_two_leg_payload())
        result = get_option_chain(client, "TEST")

        assert result["outcome"] == "ok"
        assert result["detail"] == "chain_retrieved"
        assert result["symbol"] == "TEST"

    def test_ok_filters_effective_dte_60_excludes_far_expiration(self) -> None:
        """The default cap is 60 DTE and the +70 expiration is excluded."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_two_leg_payload(extra_days=70))
        result = get_option_chain(client, "TEST")

        assert result["filters"]["dte_max_effective"] == 60
        expirations = result["expirations"]
        assert expirations, "expected at least one expiration in range"
        assert all(e["dte"] <= 60 for e in expirations)
        dates = {e["expiration_date"] for e in expirations}
        assert dates == {chain_expiry_date(7), chain_expiry_date(30)}

    def test_ok_every_strike_row_has_both_legs(self) -> None:
        """With option_type='both' each strike row carries both 'call' and 'put'."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_two_leg_payload())
        result = get_option_chain(client, "TEST")

        for expiration in result["expirations"]:
            strikes = expiration["strikes"]
            assert strikes, f"expiration {expiration['expiration_date']} has no strikes"
            for row in strikes:
                assert "call" in row, f"missing call leg at strike {row['strike']}"
                assert "put" in row, f"missing put leg at strike {row['strike']}"
                assert isinstance(row["call"], list) and row["call"]
                assert isinstance(row["put"], list) and row["put"]

    def test_ok_contract_fields_underlying_and_generated_at(self) -> None:
        """contract_fields is the complete 23-column manifest; price and
        generated_at are present."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_two_leg_payload())
        result = get_option_chain(client, "TEST")

        assert result["contract_fields"] == EXPECTED_CONTRACT_FIELDS
        assert result["underlying_price"] == 251.31
        assert isinstance(result["generated_at"], str)
        assert result["generated_at"]

    def test_sc004_one_invocation_and_no_pagination_keys(self) -> None:
        """SC-004/FR-011: exactly one provider call per invocation and the
        response contains no pagination key at any depth."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_two_leg_payload())
        result = get_option_chain(client, "TEST")

        assert len(client.calls) == 1
        assert client.calls[0]["symbol"] == "TEST"
        keys = _collect_keys(result, set())
        assert not (keys & PAGINATION_KEYS), (
            f"pagination keys leaked into the response: {sorted(keys & PAGINATION_KEYS)}"
        )


# =============================================================================
# no_options_listed
# =============================================================================


class TestNoOptionsListed:
    """An instrument without listed options yields a structured result, not an
    error (contract §4)."""

    @pytest.mark.parametrize("call_map, put_map", [(None, None), ({}, {})])
    def test_no_options_listed_structured_result(self, call_map, put_map) -> None:
        """Absent/None or empty leg maps -> outcome 'no_options_listed', no exception."""
        from schwab_mcp.options_chain import get_option_chain

        payload = build_chain_payload(call_map, put_map)
        client = FakeChainClient(payload)

        result = get_option_chain(client, "TEST")

        assert result["outcome"] == "no_options_listed"
        assert result["detail"] == "no_options_listed"
        assert result["symbol"] == "TEST"
        assert len(client.calls) == 1


class TestNoOptionsListedProvider400:
    """Regression (found live 2026-10-24): the provider rejects symbols with
    no listed options with HTTP 400 instead of empty maps.  The tool must
    still report the structured ``no_options_listed`` state (contract §4:
    "no error de transporte"), not a transport error."""

    class _RejectingClient:
        """Provider double whose chains call answers HTTP 400."""

        def __init__(self) -> None:
            self.calls = []

        def option_chains(self, symbol, **kwargs):
            self.calls.append({"symbol": symbol, **kwargs})
            return build_response(None, status=400)

    def test_provider_400_maps_to_no_options_listed(self) -> None:
        """A 400 from the chains endpoint (post-validation) is the live
        shape of "no options listed"."""
        from schwab_mcp.options_chain import get_option_chain

        client = self._RejectingClient()

        result = get_option_chain(client, "ZZZZZZ")

        assert result["outcome"] == "no_options_listed"
        assert result["detail"] == "no_options_listed"
        assert result["symbol"] == "ZZZZZZ"
        assert len(client.calls) == 1


# =============================================================================
# no_expirations_in_range
# =============================================================================


class TestNoExpirationsInRange:
    """When the DTE cap excludes every expiration, the result is structured and
    names the effective cap (contract §4)."""

    def test_no_expirations_in_range_reports_effective_cap(self) -> None:
        """Only a +90 expiration exists and dte_max=7 -> structured result with
        dte_max_effective=7 in the detail and an empty expiration list."""
        from schwab_mcp.options_chain import get_option_chain

        expiration = chain_expiry_date(90)
        call_map = build_expiration_map(expiration, "CALL", FIXTURE_STRIKES)
        put_map = build_expiration_map(expiration, "PUT", FIXTURE_STRIKES)
        payload = build_chain_payload(call_map, put_map)
        client = FakeChainClient(payload)

        result = get_option_chain(client, "TEST", dte_max=7)

        assert result["outcome"] == "no_expirations_in_range"
        assert "dte_max_effective=7" in result["detail"]
        assert result["expirations"] == []
        assert result["filters"]["dte_max_effective"] == 7
        assert len(client.calls) == 1


# =============================================================================
# FR-013: whole expiration missing -> ChainDataError, never a partial chain
# =============================================================================


class TestChainDataErrorWholeExpirationMissing:
    """FR-013: when a whole expiration (or map) comes without data the tool
    aborts with ``ChainDataError`` and never returns a partial chain."""

    def test_put_map_missing_whole_expiration_raises(self) -> None:
        """callExpDateMap has 2 expirations, putExpDateMap only one -> abort."""
        from schwab_mcp.options_chain import ChainDataError, get_option_chain

        near = chain_expiry_date(7)
        far = chain_expiry_date(30)
        call_map = {
            **build_expiration_map(near, "CALL", FIXTURE_STRIKES),
            **build_expiration_map(far, "CALL", FIXTURE_STRIKES),
        }
        put_map = build_expiration_map(near, "PUT", FIXTURE_STRIKES)
        payload = build_chain_payload(call_map, put_map)
        client = FakeChainClient(payload)

        with pytest.raises(ChainDataError):
            get_option_chain(client, "TEST")

        # No partial chain: the exception is the only outcome, and the fetch
        # still happened exactly once.
        assert len(client.calls) == 1

    def test_date_present_with_empty_contract_dict_raises(self) -> None:
        """A date key present in one map with an EMPTY contract dict {} also
        aborts (the date carries no data for that type)."""
        from schwab_mcp.options_chain import ChainDataError, get_option_chain

        near = chain_expiry_date(7)
        far = chain_expiry_date(30)
        call_map = {
            **build_expiration_map(near, "CALL", FIXTURE_STRIKES),
            **build_expiration_map(far, "CALL", FIXTURE_STRIKES),
        }
        put_map = {
            **build_expiration_map(near, "PUT", FIXTURE_STRIKES),
            far: {},
        }
        payload = build_chain_payload(call_map, put_map)
        client = FakeChainClient(payload)

        with pytest.raises(ChainDataError):
            get_option_chain(client, "TEST")

        assert len(client.calls) == 1


# =============================================================================
# extended=true (contract §2)
# =============================================================================


class TestExtended:
    """``extended=True`` adds the raw provider payload; the default omits it."""

    def test_extended_true_adds_raw_provider_payload(self) -> None:
        """result['provider'] deep-equals the raw payload returned by the double."""
        from schwab_mcp.options_chain import get_option_chain

        payload = _two_leg_payload()
        client = FakeChainClient(payload)

        result = get_option_chain(client, "TEST", extended=True)

        assert result["outcome"] == "ok"
        assert "provider" in result
        assert result["provider"] == payload

    def test_extended_false_omits_provider_key(self) -> None:
        """Without extended=True the response carries no 'provider' key."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_two_leg_payload())

        result = get_option_chain(client, "TEST")

        assert "provider" not in result


# =============================================================================
# SC-004: the full chain in one response, no pagination
# =============================================================================


class TestSc004FullChainSingleResponse:
    """SC-004/FR-011 across scenarios: every scenario completes with exactly
    one tool invocation and the ``ok`` response carries the full chain."""

    def test_full_chain_present_in_single_response(self) -> None:
        """All in-range expirations with all their strikes arrive in one
        response, after exactly one provider invocation, with no pagination."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_two_leg_payload())
        result = get_option_chain(client, "TEST")

        assert len(client.calls) == 1
        assert result["outcome"] == "ok"

        expirations = result["expirations"]
        dates = [e["expiration_date"] for e in expirations]
        assert dates == sorted(dates), "expirations must be sorted ascending"
        assert set(dates) == {chain_expiry_date(7), chain_expiry_date(30)}
        for expiration in expirations:
            row_strikes = [row["strike"] for row in expiration["strikes"]]
            assert row_strikes == sorted(row_strikes), "strikes must be sorted ascending"
            assert set(row_strikes) == set(FIXTURE_STRIKES), (
                "every fixture strike must arrive in the single response"
            )

        keys = _collect_keys(result, set())
        assert not (keys & PAGINATION_KEYS), (
            f"pagination keys leaked into the response: {sorted(keys & PAGINATION_KEYS)}"
        )


# =============================================================================
# T015 — delta scenarios end-to-end (US2, TDD red)
# =============================================================================

# Per-type delta ladders: within each type ``abs(delta)`` is monotone
# decreasing in strike, and the 0.20 anchors sit at DIFFERENT strikes for
# calls and puts (SC-005 fixture).  Windows are the anchor index i in the
# type's ascending-strike sequence plus DELTA_WINDOW_SIDE=2 contiguous
# strikes each side (clipped to what exists).
DELTA_LADDER_STRIKES = [240.0, 243.0, 246.0, 249.0, 252.0, 255.0, 258.0, 261.0, 264.0]
PUT_DELTAS = [-0.92, -0.80, -0.62, -0.40, -0.21, -0.13, -0.08, -0.05, -0.03]
CALL_DELTAS = [0.95, 0.85, 0.70, 0.50, 0.33, 0.22, 0.14, 0.09, 0.05]

# Anchor puts: 252.0 (|delta| = 0.21) -> indices 2..6.
PUT_DELTA_WINDOW = {246.0, 249.0, 252.0, 255.0, 258.0}
# Anchor calls: 255.0 (|delta| = 0.22) -> indices 3..7.
CALL_DELTA_WINDOW = {249.0, 252.0, 255.0, 258.0, 261.0}

# Standard fixture expirations (all inside the default 60-DTE cap).
DELTA_EXPIRATION_DAYS = (7, 30, 50)

# Deep-ITM ladders: every |delta| > 0.20 -> target NOT bracketed.
ABOVE_STRIKES = [240.0, 245.0, 250.0, 255.0, 260.0, 265.0]
ABOVE_PUT_DELTAS = [-0.95, -0.88, -0.80, -0.72, -0.65, -0.60]
ABOVE_CALL_DELTAS = [0.97, 0.93, 0.87, 0.80, 0.72, 0.65]
# Anchor puts: 265.0 (|delta| = 0.60), clipped window -> indices 3..5.
ABOVE_PUT_WINDOW = {255.0, 260.0, 265.0}

# Far-OTM ladders: every |delta| < 0.20 -> target NOT bracketed.
BELOW_STRIKES = [240.0, 243.0, 246.0, 249.0, 252.0, 255.0, 258.0, 261.0, 264.0]
BELOW_PUT_DELTAS = [-0.18, -0.15, -0.12, -0.10, -0.08, -0.06, -0.05, -0.04, -0.03]
BELOW_CALL_DELTAS = [0.19, 0.16, 0.13, 0.11, 0.09, 0.07, 0.06, 0.05, 0.04]
# Anchor puts: 240.0 (|delta| = 0.18), clipped window -> indices 0..2.
BELOW_PUT_WINDOW = {240.0, 243.0, 246.0}


def _delta_payload(days, strikes, put_deltas, call_deltas) -> dict:
    """Chain payload with explicit per-type delta ladders on every expiration."""
    call_map: dict = {}
    put_map: dict = {}
    for days_ahead in days:
        expiration = chain_expiry_date(days_ahead)
        call_map.update(
            build_expiration_map(expiration, "CALL", list(strikes), deltas=list(call_deltas))
        )
        put_map.update(
            build_expiration_map(expiration, "PUT", list(strikes), deltas=list(put_deltas))
        )
    return build_chain_payload(call_map, put_map)


def _standard_delta_payload() -> dict:
    """3-expiration payload with the standard CALL/PUT ladders above."""
    return _delta_payload(
        DELTA_EXPIRATION_DAYS, DELTA_LADDER_STRIKES, PUT_DELTAS, CALL_DELTAS
    )


def _type_strike_sets(expiration: dict) -> dict:
    """Per-leg strike sets of one expiration keyed by StrikeRow leg name."""
    calls: set = set()
    puts: set = set()
    for row in expiration["strikes"]:
        if "call" in row:
            calls.add(row["strike"])
        if "put" in row:
            puts.add(row["strike"])
    return {"call": calls, "put": puts}


# =============================================================================
# Delta scenario — puts-only (quickstart S2 steps 1-2)
# =============================================================================


class TestDeltaScenarioPutsOnly:
    """``option_type="puts"``, ``delta_target=0.20`` over 3 expirations.

    Only ``put`` legs, exactly the 5-strike window centered on the
    ``abs(delta) ≈ 0.20`` contract, and one provider call with the internal
    ``strikeCount`` floor (brief orchestration step 2).
    """

    def test_put_legs_only_with_exact_delta_window_per_expiration(self) -> None:
        """Rows carry only 'put' keys and the exact anchor ± 2 window."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_standard_delta_payload())
        result = get_option_chain(client, "TEST", option_type="puts", delta_target=0.20)

        assert result["outcome"] == "ok"
        assert result["filters"]["delta_target"] == 0.20
        expirations = result["expirations"]
        assert {e["expiration_date"] for e in expirations} == {
            chain_expiry_date(d) for d in DELTA_EXPIRATION_DAYS
        }
        for expiration in expirations:
            rows = expiration["strikes"]
            assert rows, f"expiration {expiration['expiration_date']} has no strikes"
            for row in rows:
                assert "put" in row, f"missing put leg at strike {row['strike']}"
                assert "call" not in row, f"unexpected call leg at strike {row['strike']}"
            sets = _type_strike_sets(expiration)
            assert len(sets["put"]) <= 5, "delta window is at most 5 strikes per type"
            assert sets["put"] == PUT_DELTA_WINDOW, (
                f"expiration {expiration['expiration_date']}: expected the "
                f"abs(delta)≈0.20 anchor ± 2 window {sorted(PUT_DELTA_WINDOW)}, "
                f"got {sorted(sets['put'])}"
            )

    def test_single_provider_call_with_internal_strike_count_floor(self) -> None:
        """The bracketed fetch is a single call with strikeCount = max(50, 100)."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_standard_delta_payload())
        get_option_chain(client, "TEST", option_type="puts", delta_target=0.20)

        assert len(client.calls) == 1
        assert client.calls[0]["symbol"] == "TEST"
        assert client.calls[0]["contractType"] == "PUT"
        assert client.calls[0]["strikeCount"] == 100, (
            "delta fetch must use strikeCount = max(max_strikes, 100)"
        )


# =============================================================================
# Delta scenario — both types, per-type windows (quickstart S2 step 3, SC-005)
# =============================================================================


class TestDeltaScenarioBothTypesPerTypeWindows:
    """``option_type="both"``, ``delta_target=0.20``: independent per-type
    windows around DIFFERENT anchors (SC-005 / clarification 2026-10-23)."""

    def test_per_type_windows_are_independent_per_expiration(self) -> None:
        """Up to 5 CALL strikes and up to 5 PUT strikes per expiration, each
        window centered on its own type's abs(delta) ≈ 0.20 anchor."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_standard_delta_payload())
        result = get_option_chain(client, "TEST", option_type="both", delta_target=0.20)

        assert result["outcome"] == "ok"
        expirations = result["expirations"]
        assert {e["expiration_date"] for e in expirations} == {
            chain_expiry_date(d) for d in DELTA_EXPIRATION_DAYS
        }
        for expiration in expirations:
            sets = _type_strike_sets(expiration)
            assert len(sets["call"]) <= 5, "at most 5 CALL strikes per expiration"
            assert len(sets["put"]) <= 5, "at most 5 PUT strikes per expiration"
            assert sets["call"] == CALL_DELTA_WINDOW, (
                f"expiration {expiration['expiration_date']}: CALL window "
                f"{sorted(sets['call'])} != {sorted(CALL_DELTA_WINDOW)}"
            )
            assert sets["put"] == PUT_DELTA_WINDOW, (
                f"expiration {expiration['expiration_date']}: PUT window "
                f"{sorted(sets['put'])} != {sorted(PUT_DELTA_WINDOW)}"
            )

    def test_row_strikes_are_union_with_per_type_leg_keys(self) -> None:
        """Row strikes = union of the two windows; each leg key appears only
        when that type selected the strike."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_standard_delta_payload())
        result = get_option_chain(client, "TEST", option_type="both", delta_target=0.20)

        expected_union = CALL_DELTA_WINDOW | PUT_DELTA_WINDOW
        for expiration in result["expirations"]:
            rows = {row["strike"]: row for row in expiration["strikes"]}
            assert set(rows) == expected_union, (
                f"expiration {expiration['expiration_date']}: row strikes "
                f"{sorted(rows)} != union {sorted(expected_union)}"
            )
            for strike, row in rows.items():
                assert ("call" in row) == (strike in CALL_DELTA_WINDOW), (
                    f"strike {strike}: 'call' leg key must follow the CALL window"
                )
                assert ("put" in row) == (strike in PUT_DELTA_WINDOW), (
                    f"strike {strike}: 'put' leg key must follow the PUT window"
                )

    def test_single_provider_call_when_both_types_bracketed(self) -> None:
        """Both ladders span 0.20 -> exactly one fetch with the 100 floor."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_standard_delta_payload())
        get_option_chain(client, "TEST", option_type="both", delta_target=0.20)

        assert len(client.calls) == 1
        assert client.calls[0]["contractType"] == "ALL"
        assert client.calls[0]["strikeCount"] == 100


# =============================================================================
# SC-004 across delta scenarios: one tool invocation, no pagination
# =============================================================================


class TestDeltaScenariosSc004SingleInvocation:
    """Each delta scenario completes with exactly ONE ``get_option_chain``
    invocation whose response carries the complete chain and no pagination
    key at any depth (SC-004 / FR-011)."""

    @pytest.mark.parametrize(
        "option_type, expected_call_strikes, expected_put_strikes",
        [
            ("puts", set(), PUT_DELTA_WINDOW),
            ("both", CALL_DELTA_WINDOW, PUT_DELTA_WINDOW),
        ],
        ids=["puts-only", "both-types"],
    )
    def test_one_invocation_returns_complete_chain_without_pagination(
        self, option_type, expected_call_strikes, expected_put_strikes
    ) -> None:
        """A single call serves the whole scenario: every expiration and every
        selected strike arrives at once, with no cursor/offset anywhere."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_standard_delta_payload())
        # Exactly ONE tool invocation per scenario (SC-004): the assertion is
        # that this single call already returns the complete chain below.
        result = get_option_chain(client, "TEST", option_type=option_type, delta_target=0.20)

        assert result["outcome"] == "ok"
        expirations = result["expirations"]
        dates = [e["expiration_date"] for e in expirations]
        assert dates == sorted(dates), "expirations must be sorted ascending"
        assert set(dates) == {chain_expiry_date(d) for d in DELTA_EXPIRATION_DAYS}
        for expiration in expirations:
            row_strikes = [row["strike"] for row in expiration["strikes"]]
            assert row_strikes == sorted(row_strikes), "strikes must be sorted ascending"
            sets = _type_strike_sets(expiration)
            assert sets["call"] == expected_call_strikes
            assert sets["put"] == expected_put_strikes

        keys = _collect_keys(result, set())
        assert not (keys & PAGINATION_KEYS), (
            f"pagination keys leaked into the response: {sorted(keys & PAGINATION_KEYS)}"
        )


# =============================================================================
# Internal strikeCount expansion (brief orchestration step 2 / research R2)
# =============================================================================


class TestDeltaStrikeCountExpansion:
    """``strikeCount = max(max_strikes, 100)`` on the first delta fetch, and a
    single re-fetch with ``strikeCount = 200`` when the target is not
    bracketed — observable through the provider double's call log."""

    def test_bracketed_target_fetches_once_with_floor(self) -> None:
        """Ladder spans 0.20 -> exactly ONE call with
        strikeCount = max(max_strikes=10, 100) = 100 and no re-fetch."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_standard_delta_payload())
        result = get_option_chain(
            client, "TEST", max_strikes=10, option_type="puts", delta_target=0.20
        )

        assert result["outcome"] == "ok"
        assert len(client.calls) == 1, "bracketed target must not trigger a re-fetch"
        assert client.calls[0]["strikeCount"] == 100, (
            "first delta fetch must use strikeCount = max(max_strikes, 100)"
        )
        for expiration in result["expirations"]:
            assert _type_strike_sets(expiration)["put"] == PUT_DELTA_WINDOW

    @pytest.mark.parametrize(
        "strikes, put_deltas, call_deltas, expected_put_window",
        [
            (ABOVE_STRIKES, ABOVE_PUT_DELTAS, ABOVE_CALL_DELTAS, ABOVE_PUT_WINDOW),
            (BELOW_STRIKES, BELOW_PUT_DELTAS, BELOW_CALL_DELTAS, BELOW_PUT_WINDOW),
        ],
        ids=["all-abs-delta-above-target", "all-abs-delta-below-target"],
    )
    def test_not_bracketed_target_single_refetch_with_ceiling(
        self, strikes, put_deltas, call_deltas, expected_put_window
    ) -> None:
        """All fetched abs(delta) on one side of the target -> exactly TWO
        calls: strikeCount 100 then 200.  The tool still completes in one
        invocation with the closest available contracts (≤ 5 per type) and
        never issues a third call."""
        from schwab_mcp.options_chain import get_option_chain

        payload = _delta_payload((7, 30), strikes, put_deltas, call_deltas)
        client = FakeChainClient(payload)
        result = get_option_chain(client, "TEST", option_type="puts", delta_target=0.20)

        assert result["outcome"] == "ok"
        assert [c["strikeCount"] for c in client.calls] == [100, 200], (
            "expected exactly one floor fetch and one ceiling re-fetch"
        )
        for expiration in result["expirations"]:
            sets = _type_strike_sets(expiration)
            assert sets["call"] == set()
            assert sets["put"] == expected_put_window, (
                f"expiration {expiration['expiration_date']}: expected the "
                f"closest available window {sorted(expected_put_window)}, "
                f"got {sorted(sets['put'])}"
            )
        keys = _collect_keys(result, set())
        assert not (keys & PAGINATION_KEYS), (
            f"pagination keys leaked into the response: {sorted(keys & PAGINATION_KEYS)}"
        )


# =============================================================================
# Delta window never overrides the DTE cap
# =============================================================================


class TestDeltaRespectsDteCap:
    """``delta_target`` selection applies only inside the DTE filter
    (research R3): expirations beyond ``dte_max`` stay excluded."""

    def test_dte_cap_excludes_far_expirations_under_delta(self) -> None:
        """With delta_target=0.20 and dte_max=30, the +50 expiration is
        excluded while the in-range expirations keep their delta windows."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_standard_delta_payload())
        result = get_option_chain(
            client, "TEST", option_type="puts", delta_target=0.20, dte_max=30
        )

        assert result["outcome"] == "ok"
        assert result["filters"]["dte_max_effective"] == 30
        expirations = result["expirations"]
        dates = {e["expiration_date"] for e in expirations}
        assert dates == {chain_expiry_date(7), chain_expiry_date(30)}
        for expiration in expirations:
            assert expiration["dte"] <= 30, "delta window never overrides the DTE cap"
            sets = _type_strike_sets(expiration)
            assert sets["put"] == PUT_DELTA_WINDOW
            assert sets["call"] == set()


# =============================================================================
# T018 — explicit limits end-to-end (US3: quickstart S3, SC-006 / SC-004)
# =============================================================================

# Wide ladder: 41 strikes 230..270 step 1 around the 250.0 underlying so
# ``max_strikes=10`` actually trims both sides of the money.
US3_WIDE_STRIKES = [230.0 + 1.0 * i for i in range(41)]
US3_UNDERLYING = 250.0
# Expiration ladder crossing every US3 DTE scenario (+150 beyond all caps).
US3_EXPIRATION_DAYS = (7, 30, 90, 120, 150)


def _us3_payload(days=US3_EXPIRATION_DAYS) -> dict:
    """Multi-expiration, both-leg payload over the wide strike ladder."""
    call_map: dict = {}
    put_map: dict = {}
    for days_ahead in days:
        expiration = chain_expiry_date(days_ahead)
        call_map.update(build_expiration_map(expiration, "CALL", list(US3_WIDE_STRIKES)))
        put_map.update(build_expiration_map(expiration, "PUT", list(US3_WIDE_STRIKES)))
    return build_chain_payload(call_map, put_map, underlying_price=US3_UNDERLYING)


def _expected_strike_window(strikes, atm, max_strikes) -> list:
    """Deterministic selection window (data-model §3): up to *max_strikes*
    nearest strikes ``<= atm`` UNION up to *max_strikes* nearest strikes
    ``>= atm`` (ATM included if it exists)."""
    below = sorted((s for s in strikes if s <= atm), reverse=True)[:max_strikes]
    above = sorted(s for s in strikes if s >= atm)[:max_strikes]
    return sorted(set(below) | set(above))


class TestSc006ExplicitLimits:
    """SC-006: requested limits (strikes per side, option types, DTE) are
    respected at 100% — zero out-of-bounds contracts in the response."""

    def test_max_strikes_10_and_dte_max_30_zero_out_of_bounds(self) -> None:
        """``max_strikes=10, option_type='both', dte_max=30`` over a
        multi-expiration fixture: every strike sits inside the permitted
        window (<= 10 per side of ``atm_strike``), every dte <= 30, and every
        row carries legs only for the included types."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_us3_payload())
        result = get_option_chain(
            client, "TEST", max_strikes=10, option_type="both", dte_max=30
        )

        assert result["outcome"] == "ok"
        assert result["filters"]["dte_max_effective"] == 30
        expirations = result["expirations"]
        assert {e["expiration_date"] for e in expirations} == {
            chain_expiry_date(7),
            chain_expiry_date(30),
        }, "only expirations with dte <= 30 may be returned"

        for expiration in expirations:
            assert expiration["dte"] <= 30, "zero out-of-bounds DTE contracts"
            atm = expiration["atm_strike"]
            assert atm == US3_UNDERLYING
            rows = expiration["strikes"]
            row_strikes = [row["strike"] for row in rows]

            # exact permitted window — zero strikes outside it
            assert row_strikes == _expected_strike_window(US3_WIDE_STRIKES, atm, 10)
            assert len([s for s in row_strikes if s <= atm]) <= 10
            assert len([s for s in row_strikes if s >= atm]) <= 10
            assert atm in row_strikes
            assert len(rows) <= 2 * 10

            for row in rows:
                assert set(row) == {"strike", "call", "put"}, (
                    f"strike {row['strike']}: legs only for included types "
                    f"(option_type='both' -> call+put, nothing else)"
                )

    def test_dte_max_120_includes_up_to_120_and_excludes_beyond(self) -> None:
        """``dte_max=120``: expirations up to +120 included, +150 excluded,
        and the strike window stays within ``max_strikes=10`` per side."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_us3_payload())
        result = get_option_chain(
            client, "TEST", max_strikes=10, option_type="both", dte_max=120
        )

        assert result["outcome"] == "ok"
        assert result["filters"]["dte_max_effective"] == 120
        expirations = result["expirations"]
        assert {e["expiration_date"] for e in expirations} == {
            chain_expiry_date(7),
            chain_expiry_date(30),
            chain_expiry_date(90),
            chain_expiry_date(120),
        }, "expirations up to +120 included, +150 excluded"
        assert chain_expiry_date(150) not in {
            e["expiration_date"] for e in expirations
        }

        for expiration in expirations:
            assert expiration["dte"] <= 120, "zero out-of-bounds DTE contracts"
            atm = expiration["atm_strike"]
            rows = expiration["strikes"]
            row_strikes = [row["strike"] for row in rows]
            assert row_strikes == _expected_strike_window(US3_WIDE_STRIKES, atm, 10)
            assert len([s for s in row_strikes if s <= atm]) <= 10
            assert len([s for s in row_strikes if s >= atm]) <= 10
            for row in rows:
                assert set(row) == {"strike", "call", "put"}

    def test_option_type_calls_returns_call_legs_only(self) -> None:
        """``option_type='calls'``: zero put contracts in the response — rows
        carry the ``call`` leg key only (SC-006 option-type limit)."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_us3_payload())
        result = get_option_chain(
            client, "TEST", max_strikes=10, option_type="calls", dte_max=30
        )

        assert result["outcome"] == "ok"
        for expiration in result["expirations"]:
            for row in expiration["strikes"]:
                assert set(row) == {"strike", "call"}, (
                    f"strike {row['strike']}: unexpected leg key for "
                    f"option_type='calls'"
                )


class TestSc004SingleInvocationUs3:
    """SC-004 across US3 scenarios: each scenario completes with EXACTLY one
    provider invocation and the ``ok``/structured response carries no
    pagination key at any depth (FR-011)."""

    @pytest.mark.parametrize(
        "payload_days, kwargs, expected_outcome",
        [
            (US3_EXPIRATION_DAYS, {"max_strikes": 10, "dte_max": 30}, "ok"),
            ((10, 30), {"dte_max": 7}, "no_expirations_in_range"),
            (US3_EXPIRATION_DAYS, {"dte_max": 120}, "ok"),
        ],
        ids=["max_strikes-10", "dte_max-7-empty-range", "dte_max-120"],
    )
    def test_one_invocation_per_scenario_without_pagination(
        self, payload_days, kwargs, expected_outcome
    ) -> None:
        """One tool invocation returns the full result: exactly one provider
        call and no cursor/offset/has_more anywhere in the response."""
        from schwab_mcp.options_chain import get_option_chain

        client = FakeChainClient(_us3_payload(days=payload_days))
        result = get_option_chain(client, "TEST", **kwargs)

        assert result["outcome"] == expected_outcome
        assert len(client.calls) == 1, (
            "SC-004: exactly one provider invocation per scenario"
        )
        assert client.calls[0]["symbol"] == "TEST"

        keys = _collect_keys(result, set())
        assert not (keys & PAGINATION_KEYS), (
            f"pagination keys leaked into the response: {sorted(keys & PAGINATION_KEYS)}"
        )
