"""Failing unit tests for option-chain payload mapping (TDD red-phase).

Tests for ``serialize_leg(contract)`` and ``build_chain_result(payload, query)``
that will map a Schwab ``option_chains`` payload into the curated chain
response: ``CONTRACT_FIELDS`` column order, per-leg rounding, expiration
union/mapping, ``dte``, ``atm_strike``, StrikeRow leg semantics and response
metadata.

The mapping functions do NOT exist yet — every test that reaches for them
fails with ``ImportError`` (Red). Once implemented (T010), all tests should
pass.

References
----------
- tmp/008-api-brief.md: binding API contract (Mapping / selection section)
- specs/008-extract-option-chain/data-model.md: §1 entities + contract field
  order, §2 relations (union of ``*ExpDateMap`` keys), §3 deterministic
  selection
- specs/008-extract-option-chain/tasks.md: T006
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from tests.unit.helpers import (
    build_chain_payload,
    build_contract,
    build_expiration_map,
    chain_expiry_date,
)


# =============================================================================
# Expectations derived from data-model.md §1 (ContractFields, exact order)
# =============================================================================

EXPECTED_CONTRACT_FIELDS: tuple[str, ...] = (
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

_TRADE_TIME_EPOCH_MS = 1792854000000
_EXPECTED_TRADE_TIME_ISO = datetime.fromtimestamp(
    _TRADE_TIME_EPOCH_MS / 1000, timezone.utc
).isoformat(timespec="seconds")


def _index(name: str) -> int:
    """Column position of *name* in the fixed ``CONTRACT_FIELDS`` order."""
    return EXPECTED_CONTRACT_FIELDS.index(name)


def _raw_leg(contract: dict) -> list:
    """Serialize *contract* with no length assumptions (raw provider array)."""
    from schwab_mcp.options_chain import serialize_leg

    return list(serialize_leg(contract))


def _leg(contract: dict) -> list:
    """Serialize *contract* and pad to the full 23-column layout.

    The contract allows a shorter array when **trailing** values are ``None``
    (a full-length array with trailing ``null``s is equally valid), so
    positional index checks pad missing trailing columns with ``None``.
    """
    leg = _raw_leg(contract)
    assert len(leg) <= len(EXPECTED_CONTRACT_FIELDS), (
        "leg array must never be longer than CONTRACT_FIELDS"
    )
    return leg + [None] * (len(EXPECTED_CONTRACT_FIELDS) - len(leg))


def _query(**kwargs):
    """Build an ``OptionChainQuery`` with test-friendly defaults."""
    from schwab_mcp.options_chain import OptionChainQuery

    return OptionChainQuery(symbol="TEST", **kwargs)


def _single_expiration_payload(
    strikes: list[float] | None = None,
    *,
    days_ahead: int = 7,
    underlying_price: float = 251.31,
    is_delayed: bool = False,
):
    """Payload with one expiration where CALL and PUT maps share date+strikes."""
    strikes = strikes if strikes is not None else [245.0, 250.0, 255.0]
    exp = chain_expiry_date(days_ahead)
    calls = build_expiration_map(exp, "CALL", strikes)
    puts = build_expiration_map(exp, "PUT", strikes)
    return (
        build_chain_payload(
            calls, puts, underlying_price=underlying_price, is_delayed=is_delayed
        ),
        exp,
    )


# =============================================================================
# Test class: CONTRACT_FIELDS constant (data-model.md §1)
# =============================================================================


class TestContractFields:
    """``CONTRACT_FIELDS`` is the fixed 23-column leg layout, in order."""

    def test_contract_fields_exact_23_tuple_in_order(self) -> None:
        """``CONTRACT_FIELDS`` equals the data-model §1 order exactly."""
        from schwab_mcp.options_chain import CONTRACT_FIELDS

        assert CONTRACT_FIELDS == EXPECTED_CONTRACT_FIELDS

    def test_contract_fields_count_and_uniqueness(self) -> None:
        """The layout has exactly 23 distinct columns."""
        from schwab_mcp.options_chain import CONTRACT_FIELDS

        assert len(CONTRACT_FIELDS) == 23
        assert len(set(CONTRACT_FIELDS)) == 23


# =============================================================================
# Test class: serialize_leg — per-column rounding and missing fields
# =============================================================================


class TestSerializeLeg:
    """``serialize_leg(contract)`` returns a positional array aligned with
    ``CONTRACT_FIELDS``: prices rounded to 2 decimals, greeks/IV to 4,
    integers unrounded, ``trade_time`` epoch-ms → ISO, ``deliverable_note``
    passthrough, missing source fields → explicit ``None`` (FR-007).
    """

    def test_leg_is_list_positionally_aligned_with_contract_fields(self) -> None:
        """A realistic CALL contract serializes to the 23-column layout."""
        contract = build_contract("CALL", 250.0)
        leg = _leg(contract)

        assert isinstance(leg, list)
        assert leg[_index("bid")] == round(contract["bid"], 2)
        assert leg[_index("ask")] == round(contract["ask"], 2)
        assert leg[_index("volume")] == contract["totalVolume"]
        assert leg[_index("open_interest")] == contract["openInterest"]
        assert leg[_index("iv")] == round(contract["volatility"], 4)
        assert leg[_index("delta")] == round(contract["delta"], 4)

    def test_price_fields_rounded_to_two_decimals(self) -> None:
        """Prices/values round with ``round(v, 2)`` — including values that
        land on a rounding edge (expected computed with ``round()``)."""
        edge = 12.345  # 12.345 -> round(12.345, 2), Python-equal expectation
        contract = build_contract(
            "CALL",
            250.0,
            bid=edge,
            ask=edge,
            last=edge,
            mark=edge,
            markChange=edge,
            markPercentChange=edge,
            highPrice=edge,
            lowPrice=edge,
            openPrice=edge,
            closePrice=edge,
            theoreticalOptionValue=edge,
            timeValue=edge,
        )
        leg = _leg(contract)

        expected = round(edge, 2)
        for name in (
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
        ):
            assert leg[_index(name)] == expected, name

    def test_price_rounding_matches_builtin_round_exactly(self) -> None:
        """Rounding is exactly ``round(v, 2)`` (banker's rounding included)."""
        contract = build_contract("CALL", 250.0, bid=12.345, ask=12.341)
        leg = _leg(contract)

        assert leg[_index("bid")] == round(12.345, 2)
        assert leg[_index("ask")] == round(12.341, 2)

    def test_greeks_and_iv_rounded_to_four_decimals(self) -> None:
        """``iv, delta, gamma, theta, vega, rho`` round with ``round(v, 4)``."""
        values = {
            "volatility": 0.12345,
            "gamma": 0.03105,
            "theta": -0.08445,
            "vega": 0.06225,
            "rho": -0.01185,
        }
        contract = build_contract("CALL", 250.0, delta=0.12345, **values)
        leg = _leg(contract)

        assert leg[_index("iv")] == round(values["volatility"], 4)
        assert leg[_index("delta")] == round(0.12345, 4)
        assert leg[_index("gamma")] == round(values["gamma"], 4)
        assert leg[_index("theta")] == round(values["theta"], 4)
        assert leg[_index("vega")] == round(values["vega"], 4)
        assert leg[_index("rho")] == round(values["rho"], 4)

    def test_integer_fields_pass_through_unrounded(self) -> None:
        """``volume``, ``open_interest`` and ``multiplier`` are reported as-is."""
        contract = build_contract(
            "CALL",
            250.0,
            totalVolume=12345,
            openInterest=6789,
            multiplier=100,
        )
        leg = _leg(contract)

        assert leg[_index("volume")] == 12345
        assert leg[_index("open_interest")] == 6789
        assert leg[_index("multiplier")] == 100
        assert isinstance(leg[_index("volume")], int)
        assert isinstance(leg[_index("open_interest")], int)
        assert isinstance(leg[_index("multiplier")], int)

    def test_trade_time_epoch_ms_converted_to_iso(self) -> None:
        """``tradeTime`` (epoch ms) converts via
        ``datetime.fromtimestamp(v/1000, timezone.utc).isoformat(timespec="seconds")``."""
        contract = build_contract("CALL", 250.0)  # tradeTime = 1792854000000
        leg = _leg(contract)

        assert leg[_index("trade_time")] == _EXPECTED_TRADE_TIME_ISO
        assert leg[_index("trade_time")] == datetime.fromtimestamp(
            _TRADE_TIME_EPOCH_MS / 1000, timezone.utc
        ).isoformat(timespec="seconds")

    def test_trade_time_already_string_passes_through(self) -> None:
        """An already-string ``tradeTime`` passes through unchanged."""
        raw = "2026-10-24T15:00:00+00:00"
        contract = build_contract("CALL", 250.0, tradeTime=raw)
        leg = _leg(contract)

        assert leg[_index("trade_time")] == raw

    def test_trade_time_missing_is_none(self) -> None:
        """A missing ``tradeTime`` yields ``None`` in its column."""
        contract = build_contract("CALL", 250.0, tradeTime=None)
        leg = _leg(contract)

        assert leg[_index("trade_time")] is None

    def test_deliverable_note_passthrough(self) -> None:
        """``deliverableNote`` passes through as-is (default ``None``)."""
        note = "DELIVER 100 SHARES OF TEST"
        contract = build_contract("CALL", 250.0, deliverableNote=note)
        leg = _leg(contract)

        assert len(leg) == 23  # trailing value present -> full-length array
        assert leg[_index("deliverable_note")] == note

        default_leg = _leg(build_contract("CALL", 250.0))
        assert default_leg[_index("deliverable_note")] is None

    def test_missing_fields_map_to_explicit_none(self) -> None:
        """Missing/``None`` source fields are explicit ``None`` in their own
        column — never invented, and never shifting neighbours (FR-007)."""
        contract = build_contract("PUT", 250.0)
        contract.update(
            {
                "delta": None,
                "markChange": None,
                "theoreticalOptionValue": None,
                "deliverableNote": None,
            }
        )
        raw = _raw_leg(contract)

        # Only the trailing column may be trimmed; middle columns keep position.
        assert len(raw) >= 22
        leg = _leg(contract)
        assert leg[_index("delta")] is None
        assert leg[_index("mark_change")] is None
        assert leg[_index("theoretical_value")] is None
        assert leg[_index("deliverable_note")] is None
        # Neighbours of the nulled columns are still present and aligned.
        assert leg[_index("gamma")] is not None
        assert leg[_index("mark_pct_change")] is not None
        assert leg[_index("time_value")] is not None

    def test_leg_length_is_full_or_trims_only_trailing_nones(self) -> None:
        """The array is 23 long, or shorter only when trailing values are
        ``None`` (contract §2)."""
        full = build_contract("CALL", 250.0, deliverableNote="note")
        assert len(_raw_leg(full)) == 23

        default = build_contract("CALL", 250.0)  # deliverableNote=None
        leg = _raw_leg(default)
        assert 22 <= len(leg) <= 23


# =============================================================================
# Test class: build_chain_result — expiration union, dte, atm_strike
# =============================================================================


class TestMapExpirations:
    """``build_chain_result`` keys expirations by ``*ExpDateMap`` date keys
    (union of both maps), sorted ascending, with calendar-day ``dte`` and an
    ``atm_strike`` closest to ``underlying_price``."""

    def test_union_of_call_and_put_maps_keyed_by_expiration_date(self) -> None:
        """Expiration keys come from the union of both ``*ExpDateMap`` maps
        and strike rows from the union of the legs' strikes (data-model §2).

        Note (FR-013, clarification 2026-10-23): the union applies at the
        strike level — a strike present in only one map keeps that leg only.
        Date-level asymmetry across included types is a partial chain and
        raises ``ChainDataError`` (covered by the integration suite); both
        maps here share their date keys.
        """
        exp_a = chain_expiry_date(7)
        exp_b = chain_expiry_date(30)
        calls = {
            **build_expiration_map(exp_a, "CALL", [245.0, 250.0, 255.0]),
            **build_expiration_map(exp_b, "CALL", [250.0]),
        }
        puts = {
            **build_expiration_map(exp_a, "PUT", [248.0, 250.0]),
            **build_expiration_map(exp_b, "PUT", [250.0, 252.0]),
        }
        payload = build_chain_payload(calls, puts, underlying_price=251.31)

        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(payload, _query())

        assert result["outcome"] == "ok"
        dates = [e["expiration_date"] for e in result["expirations"]]
        assert sorted(dates) == sorted([exp_a, exp_b])
        # Strike-level union: a strike present in only one map keeps that leg.
        by_date = {e["expiration_date"]: e for e in result["expirations"]}
        rows_a = {row["strike"]: row for row in by_date[exp_a]["strikes"]}
        assert sorted(rows_a) == [245.0, 248.0, 250.0, 255.0]
        assert "call" in rows_a[245.0] and "put" not in rows_a[245.0]
        assert "put" in rows_a[248.0] and "call" not in rows_a[248.0]
        assert "call" in rows_a[250.0] and "put" in rows_a[250.0]
        assert "call" in rows_a[255.0] and "put" not in rows_a[255.0]

    def test_expiration_map_keys_with_provider_suffix_are_normalised(self) -> None:
        """Live provider keys look like ``2026-10-26:2`` (date + suffix,
        found live 2026-10-24); the response exposes the plain
        ``YYYY-MM-DD`` date and computes ``dte`` from it."""
        exp = chain_expiry_date(7)
        key = f"{exp}:2"
        calls = {
            key: {
                f"{key}:000250000:CALL": build_contract(
                    "CALL", 250.0, expiration_date=exp
                )
            }
        }
        puts = {
            key: {
                f"{key}:000250000:PUT": build_contract(
                    "PUT", 250.0, expiration_date=exp
                )
            }
        }
        payload = build_chain_payload(calls, puts)

        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(payload, _query())

        assert result["outcome"] == "ok"
        assert [e["expiration_date"] for e in result["expirations"]] == [exp]
        assert result["expirations"][0]["dte"] == 7

    def test_provider_suffix_must_not_trigger_partial_chain_error(self) -> None:
        """Same expiration date under different key suffixes across the two
        maps is ONE expiration (found live 2026-10-24), not a FR-013
        partial chain."""
        exp = chain_expiry_date(7)
        calls = {
            f"{exp}:2": {
                f"{exp}:2:000250000:CALL": build_contract(
                    "CALL", 250.0, expiration_date=exp
                )
            }
        }
        puts = {
            f"{exp}:3": {
                f"{exp}:3:000250000:PUT": build_contract(
                    "PUT", 250.0, expiration_date=exp
                )
            }
        }
        payload = build_chain_payload(calls, puts)

        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(payload, _query())

        assert result["outcome"] == "ok"
        assert [e["expiration_date"] for e in result["expirations"]] == [exp]
        rows = result["expirations"][0]["strikes"]
        assert "call" in rows[0] and "put" in rows[0]

    def test_live_list_valued_entries_are_parsed(self) -> None:
        """Live provider entries are ``{strike_string: [contract]}`` lists
        (found live 2026-10-24); the curated rows must carry them like the
        dict-shaped fixtures."""
        exp = chain_expiry_date(7)
        call_contract = build_contract("CALL", 250.0, expiration_date=exp)
        put_contract = build_contract("PUT", 250.0, expiration_date=exp)
        payload = build_chain_payload(
            {exp: {"250.0": [call_contract]}},
            {exp: {"250.0": [put_contract]}},
        )

        from schwab_mcp.options_chain import build_chain_result, serialize_leg

        result = build_chain_result(payload, _query())

        assert result["outcome"] == "ok"
        rows = result["expirations"][0]["strikes"]
        assert [row["strike"] for row in rows] == [250.0]
        assert rows[0]["call"] == serialize_leg(call_contract)
        assert rows[0]["put"] == serialize_leg(put_contract)

    def test_live_entry_key_fallback_when_strike_price_missing(self) -> None:
        """When the contract dict lacks ``strikePrice``, the entry key is the
        strike (live shape, found live 2026-10-24)."""
        exp = chain_expiry_date(7)
        call_contract = build_contract("CALL", 250.0, expiration_date=exp)
        del call_contract["strikePrice"]
        payload = build_chain_payload(
            {exp: {"250.0": [call_contract]}},
            {exp: {"250.0": [build_contract("PUT", 250.0, expiration_date=exp)]}},
        )

        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(payload, _query())

        assert result["outcome"] == "ok"
        rows = result["expirations"][0]["strikes"]
        assert [row["strike"] for row in rows] == [250.0]

    def test_expirations_sorted_ascending_by_expiration_date(self) -> None:
        """Expirations come out sorted ascending regardless of map order."""
        exp_a = chain_expiry_date(7)
        exp_b = chain_expiry_date(30)
        # Insertion order is [B, A] in both maps.
        calls = {
            **build_expiration_map(exp_b, "CALL", [250.0]),
            **build_expiration_map(exp_a, "CALL", [250.0]),
        }
        puts = {
            **build_expiration_map(exp_b, "PUT", [250.0]),
            **build_expiration_map(exp_a, "PUT", [250.0]),
        }
        payload = build_chain_payload(calls, puts)

        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(payload, _query())

        dates = [e["expiration_date"] for e in result["expirations"]]
        assert dates == sorted(dates)
        assert dates == [exp_a, exp_b]

    def test_dte_is_calendar_days_from_today(self) -> None:
        """``dte`` is calendar days: ``(expiration_date - today).days``."""
        today = date.today()
        exp_7 = chain_expiry_date(7, today=today)
        exp_30 = chain_expiry_date(30, today=today)
        calls = {
            **build_expiration_map(exp_7, "CALL", [250.0]),
            **build_expiration_map(exp_30, "CALL", [250.0]),
        }
        puts = {
            **build_expiration_map(exp_7, "PUT", [250.0]),
            **build_expiration_map(exp_30, "PUT", [250.0]),
        }
        payload = build_chain_payload(calls, puts)

        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(payload, _query(), today=today)

        dte_by_date = {
            e["expiration_date"]: e["dte"] for e in result["expirations"]
        }
        assert dte_by_date[exp_7] == (date.fromisoformat(exp_7) - today).days == 7
        assert dte_by_date[exp_30] == (date.fromisoformat(exp_30) - today).days == 30

    def test_atm_strike_is_closest_to_underlying_price(self) -> None:
        """``atm_strike`` is the strike closest to ``underlying_price``
        (251.31 → 250.0 among 245/250/255)."""
        payload, exp = _single_expiration_payload(
            [245.0, 250.0, 255.0], underlying_price=251.31
        )

        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(payload, _query())

        expiration = next(
            e for e in result["expirations"] if e["expiration_date"] == exp
        )
        assert expiration["atm_strike"] == 250.0

    def test_atm_strike_tie_prefers_lower_strike(self) -> None:
        """On an equidistant tie the lower strike wins (251 between 250/252)."""
        payload, exp = _single_expiration_payload(
            [250.0, 252.0], underlying_price=251.0
        )

        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(payload, _query())

        expiration = next(
            e for e in result["expirations"] if e["expiration_date"] == exp
        )
        assert expiration["atm_strike"] == 250.0


# =============================================================================
# Test class: StrikeRow leg semantics (option_type → call/put keys)
# =============================================================================


class TestStrikeRowLegs:
    """Each StrikeRow carries only the legs selected for ``option_type``:
    ``both`` → call+put, ``calls`` → call only, ``puts`` → put only."""

    def _rows(self, option_type: str) -> list[dict]:
        payload, exp = _single_expiration_payload()
        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(payload, _query(option_type=option_type))
        expiration = next(
            e for e in result["expirations"] if e["expiration_date"] == exp
        )
        return expiration["strikes"]

    def test_both_keeps_both_legs_and_sorts_strikes(self) -> None:
        """``option_type="both"``: every row has BOTH ``call`` and ``put``
        when both contracts exist in the payload; strikes ascend."""
        rows = self._rows("both")

        assert rows, "expected strike rows"
        for row in rows:
            assert "call" in row
            assert "put" in row
        strikes = [row["strike"] for row in rows]
        assert strikes == sorted(strikes)

    def test_calls_keeps_only_call_leg(self) -> None:
        """``option_type="calls"``: rows have only ``call``."""
        rows = self._rows("calls")

        assert rows, "expected strike rows"
        for row in rows:
            assert "call" in row
            assert "put" not in row

    def test_puts_keeps_only_put_leg(self) -> None:
        """``option_type="puts"``: rows have only ``put``."""
        rows = self._rows("puts")

        assert rows, "expected strike rows"
        for row in rows:
            assert "put" in row
            assert "call" not in row

    def test_row_leg_is_the_serialize_leg_array(self) -> None:
        """A row's leg is exactly the ``serialize_leg`` array of its contract,
        aligned with ``CONTRACT_FIELDS`` end-to-end through the result."""
        edge_bid = 12.345
        exp = chain_expiry_date(7)
        exp_calls = build_expiration_map(
            exp, "CALL", [250.0], deltas=[0.12345], overrides={"bid": edge_bid}
        )
        payload = build_chain_payload(exp_calls, build_expiration_map(exp, "PUT", [250.0]))

        from schwab_mcp.options_chain import build_chain_result, serialize_leg

        result = build_chain_result(payload, _query(option_type="calls"))
        expiration = next(
            e for e in result["expirations"] if e["expiration_date"] == exp
        )
        row = next(r for r in expiration["strikes"] if r["strike"] == 250.0)

        contract = exp_calls[exp][next(iter(exp_calls[exp]))]

        def pad(values: list) -> list:
            return list(values) + [None] * (23 - len(values))

        leg = pad(row["call"])
        assert leg == pad(list(serialize_leg(contract)))
        # Spot-check CONTRACT_FIELDS order end-to-end through the result.
        assert leg[_index("bid")] == round(edge_bid, 2)
        assert leg[_index("delta")] == round(0.12345, 4)
        assert leg[_index("trade_time")] == _EXPECTED_TRADE_TIME_ISO
        assert leg[_index("deliverable_note")] is None


# =============================================================================
# Test class: response metadata (ChainMeta, data_state, filters echo)
# =============================================================================


class TestMetaData:
    """The ``ok`` response carries ChainMeta: outcome markers, symbol echo,
    ``generated_at``, ``data_state``, ``underlying_price``, filters echo and
    the ``contract_fields`` column order."""

    def test_ok_response_metadata(self) -> None:
        """The ok state echoes query metadata per the contract dict shape."""
        payload, _exp = _single_expiration_payload()

        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(payload, _query())

        assert result["outcome"] == "ok"
        assert result["detail"] == "chain_retrieved"
        assert result["symbol"] == "TEST"
        # generated_at must be parseable ISO-8601.
        datetime.fromisoformat(result["generated_at"])
        assert result["underlying_price"] == 251.31

    def test_filters_echo_dict_with_expected_keys(self) -> None:
        """``filters`` echoes the effective query: ``max_strikes``,
        ``option_type``, ``delta_target``, ``dte_max_requested`` and
        ``dte_max_effective``."""
        payload, _exp = _single_expiration_payload()

        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(payload, _query())
        filters = result["filters"]

        assert set(filters) == {
            "max_strikes",
            "option_type",
            "delta_target",
            "dte_max_requested",
            "dte_max_effective",
        }
        assert filters["max_strikes"] == 50
        assert filters["option_type"] == "both"
        assert filters["delta_target"] is None
        assert filters["dte_max_requested"] is None
        assert filters["dte_max_effective"] == 60

    def test_contract_fields_echo_in_response(self) -> None:
        """``contract_fields`` is ``list(CONTRACT_FIELDS)`` in the same order."""
        payload, _exp = _single_expiration_payload()

        from schwab_mcp.options_chain import CONTRACT_FIELDS, build_chain_result

        result = build_chain_result(payload, _query())

        assert result["contract_fields"] == list(CONTRACT_FIELDS)
        assert result["contract_fields"] == list(EXPECTED_CONTRACT_FIELDS)

    def test_data_state_realtime(self) -> None:
        """``is_delayed=False`` → ``data_state == "realtime"``."""
        payload, _exp = _single_expiration_payload(is_delayed=False)

        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(payload, _query())

        assert result["data_state"] == "realtime"

    def test_data_state_delayed(self) -> None:
        """``is_delayed=True`` → ``data_state == "delayed"``."""
        payload, _exp = _single_expiration_payload(is_delayed=True)

        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(payload, _query())

        assert result["data_state"] == "delayed"


# =============================================================================
# Test class: integral-float normalization (T024, TDD Red)
# =============================================================================


class TestIntegralNormalization:
    """``serialize_leg`` normalizes integral floats to ``int`` in the three
    integer columns declared by data-model §1 — ``volume``, ``open_interest``
    and ``multiplier`` ("sin redondeo ... (enteros)").

    Found live 2026-10-24: the provider sends ``multiplier`` as ``100.0``
    (and possibly integral floats for volume/open_interest); the curated
    array must report the integer ``100``, not the float. Non-integral
    values must NOT be silently truncated.
    """

    def test_multiplier_integral_float_becomes_int(self) -> None:
        """``multiplier=100.0`` → column value ``100`` typed ``int``.

        ``100.0 == 100`` is True in Python, so ``isinstance`` is what pins
        the type — the current passthrough fails only the type assertion.
        """
        contract = build_contract("CALL", 250.0, multiplier=100.0)
        leg = _leg(contract)

        assert leg[_index("multiplier")] == 100
        assert isinstance(leg[_index("multiplier")], int)

    def test_volume_and_open_interest_integral_floats_become_ints(self) -> None:
        """Integral-float ``totalVolume``/``openInterest`` → int columns."""
        contract = build_contract(
            "PUT", 250.0, totalVolume=2500.0, openInterest=920.0
        )
        leg = _leg(contract)

        assert leg[_index("volume")] == 2500
        assert isinstance(leg[_index("volume")], int)
        assert leg[_index("open_interest")] == 920
        assert isinstance(leg[_index("open_interest")], int)

    def test_non_integral_volume_is_not_truncated(self) -> None:
        """A non-integral float stays a float — no silent ``int()`` chop."""
        contract = build_contract("PUT", 250.0, totalVolume=2500.5)
        leg = _leg(contract)

        assert leg[_index("volume")] == 2500.5
        assert isinstance(leg[_index("volume")], float)

    def test_int_inputs_stay_ints(self) -> None:
        """Already-int inputs pass through unchanged and stay int-typed."""
        contract = build_contract(
            "CALL", 250.0, totalVolume=2500, openInterest=920, multiplier=100
        )
        leg = _leg(contract)

        assert isinstance(leg[_index("volume")], int)
        assert isinstance(leg[_index("open_interest")], int)
        assert isinstance(leg[_index("multiplier")], int)

    def test_end_to_end_build_chain_result_call_multiplier_is_int(self) -> None:
        """End-to-end: a payload row's ``call`` leg carries an ``int``
        multiplier column through ``build_chain_result``."""
        exp = chain_expiry_date(7)
        calls = build_expiration_map(
            exp, "CALL", [250.0], overrides={"multiplier": 100.0}
        )
        puts = build_expiration_map(exp, "PUT", [250.0])
        payload = build_chain_payload(calls, puts)

        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(payload, _query())
        expiration = next(
            e for e in result["expirations"] if e["expiration_date"] == exp
        )
        row = next(r for r in expiration["strikes"] if r["strike"] == 250.0)

        def pad(values: list) -> list:
            return list(values) + [None] * (23 - len(values))

        leg = pad(row["call"])
        assert leg[_index("multiplier")] == 100
        assert isinstance(leg[_index("multiplier")], int)
