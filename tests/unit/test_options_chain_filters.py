"""TDD Red-phase tests for provider request mapping of the option chain (T004).

These tests are written BEFORE the implementation of
``schwab_mcp.options_chain`` (the module does not exist yet).  They pin the
exact request parameters that ``fetch_option_chain`` must send upstream via
``client.option_chains(...)``.

Covers (from specs/008-extract-option-chain/tasks.md T004)
----------------------------------------------------------
- ``option_type`` → ``contractType`` mapping: ``both`` → ``ALL``,
  ``calls`` → ``CALL``, ``puts`` → ``PUT``
- ``strikeCount`` = ``max_strikes`` (50 default), overridable per call via
  ``strike_count``
- ``fromDate`` = today; ``toDate`` = today + effective DTE cap (60 default,
  or the requested ``dte_max``) — DTE in **calendar** days (research R1/R3)
- ``includeUnderlyingQuote=true``
- ``symbol`` passed as the first positional argument
- exactly ONE ``option_chains`` call per ``fetch_option_chain`` invocation
  (SC-004 foundation)
- ``fetch_option_chain`` returns the raw unwrapped payload dict

References
----------
- tmp/008-api-brief.md (binding API contract)
- specs/008-extract-option-chain/research.md (R1, R3)
- specs/008-extract-option-chain/data-model.md (§1)
"""

from __future__ import annotations

from datetime import date, timedelta

from schwab_mcp.options_chain import OptionChainQuery, fetch_option_chain

from tests.unit.helpers import build_chain_payload, build_response


# =============================================================================
# Fake client with call recording (request-mapping purposes only)
# =============================================================================


class RecordingClient:
    """Fake schwabdev client recording ``option_chains`` calls.

    Returns a minimal valid payload wrapped in a real ``requests.Response``
    so that ``provider.response_json`` unwrapping is exercised.
    """

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls: list[dict] = []

    def option_chains(self, symbol, **kwargs):
        self.calls.append({"symbol": symbol, **kwargs})
        return build_response(self._payload)


def _client() -> RecordingClient:
    return RecordingClient(build_chain_payload())


# =============================================================================
# Request mapping (T004)
# =============================================================================


class TestFetchRequestMapping:
    """``fetch_option_chain`` must map the query to provider request params."""

    # -- contractType --------------------------------------------------------

    def test_option_type_both_maps_to_contract_type_all(self) -> None:
        client = _client()
        query = OptionChainQuery(symbol="NOK", option_type="both")

        fetch_option_chain(client, query)

        assert client.calls[0]["contractType"] == "ALL"

    def test_option_type_calls_maps_to_contract_type_call(self) -> None:
        client = _client()
        query = OptionChainQuery(symbol="NOK", option_type="calls")

        fetch_option_chain(client, query)

        assert client.calls[0]["contractType"] == "CALL"

    def test_option_type_puts_maps_to_contract_type_put(self) -> None:
        client = _client()
        query = OptionChainQuery(symbol="NOK", option_type="puts")

        fetch_option_chain(client, query)

        assert client.calls[0]["contractType"] == "PUT"

    # -- strikeCount --------------------------------------------------------

    def test_default_query_sends_strike_count_50(self) -> None:
        client = _client()
        query = OptionChainQuery(symbol="NOK")

        fetch_option_chain(client, query)

        assert client.calls[0]["strikeCount"] == 50

    def test_max_strikes_maps_to_strike_count(self) -> None:
        client = _client()
        query = OptionChainQuery(symbol="NOK", max_strikes=10)

        fetch_option_chain(client, query)

        assert client.calls[0]["strikeCount"] == 10

    def test_strike_count_argument_overrides_max_strikes(self) -> None:
        client = _client()
        query = OptionChainQuery(symbol="NOK", max_strikes=10)

        fetch_option_chain(client, query, strike_count=100)

        assert client.calls[0]["strikeCount"] == 100

    # -- fromDate / toDate (calendar-day DTE window, research R1/R3) ---------

    def test_from_date_is_today(self) -> None:
        client = _client()
        query = OptionChainQuery(symbol="NOK")

        fetch_option_chain(client, query)

        assert client.calls[0]["fromDate"] == date.today().isoformat()

    def test_default_to_date_is_today_plus_60_days(self) -> None:
        client = _client()
        query = OptionChainQuery(symbol="NOK")

        fetch_option_chain(client, query)

        today = date.today()  # recomputed after the call (midnight rollover)
        expected = (today + timedelta(days=60)).isoformat()
        assert client.calls[0]["toDate"] == expected

    def test_dte_max_120_extends_to_date_to_120_calendar_days(self) -> None:
        client = _client()
        query = OptionChainQuery(symbol="NOK", dte_max=120)

        fetch_option_chain(client, query)

        today = date.today()
        expected = (today + timedelta(days=120)).isoformat()
        assert client.calls[0]["toDate"] == expected

    def test_dte_max_7_uses_calendar_days_not_trading_days(self) -> None:
        client = _client()
        query = OptionChainQuery(symbol="NOK", dte_max=7)

        fetch_option_chain(client, query)

        today = date.today()
        expected = (today + timedelta(days=7)).isoformat()
        assert client.calls[0]["toDate"] == expected

    # -- includeUnderlyingQuote / symbol ------------------------------------

    def test_include_underlying_quote_is_true(self) -> None:
        client = _client()
        query = OptionChainQuery(symbol="NOK")

        fetch_option_chain(client, query)

        assert client.calls[0]["includeUnderlyingQuote"] is True

    def test_symbol_passed_as_first_positional_argument(self) -> None:
        client = _client()
        query = OptionChainQuery(symbol="AAPL")

        fetch_option_chain(client, query)

        assert client.calls[0]["symbol"] == "AAPL"

    # -- single upcall / return value (SC-004 foundation) -------------------

    def test_exactly_one_option_chains_call_per_invocation(self) -> None:
        client = _client()
        query = OptionChainQuery(symbol="NOK")

        fetch_option_chain(client, query)

        assert len(client.calls) == 1

    def test_returns_raw_unwrapped_payload_dict(self) -> None:
        payload = build_chain_payload()
        client = RecordingClient(payload)
        query = OptionChainQuery(symbol="NOK")

        result = fetch_option_chain(client, query)

        assert result == payload
        assert isinstance(result, dict)


# =============================================================================
# Default filters (T007) — TDD Red: ``build_chain_result`` does not exist yet.
#
# Every import is lazy (inside each test body) so the T004 suite above keeps
# passing while only the new names are missing from ``schwab_mcp.options_chain``.
# Covers specs/008-extract-option-chain/data-model.md §3 (selection algorithms)
# and §1 (StrikeRow leg semantics), per tmp/008-api-brief.md.
# =============================================================================


class TestStrikeWindow:
    """Per-expiration symmetric strike window around ``atm_strike`` (T007).

    Without ``delta_target``: the up-to-``max_strikes`` nearest strikes
    ``<= atm_strike`` UNION the up-to-``max_strikes`` nearest strikes
    ``>= atm_strike`` (ATM included if it exists).  Fewer available -> all.
    Row total <= 2 * max_strikes.
    """

    def test_default_max_strikes_keeps_up_to_50_strikes_each_side(self) -> None:
        """150-strike chain: 50 below ATM union 50 above ATM around the ATM.

        The ATM strike is shared by both sides, so the union holds
        ``2 * 50 - 1 = 99`` rows.  Expected values are derived from the
        fixture, not hardcoded.
        """
        from schwab_mcp.options_chain import OptionChainQuery, build_chain_result
        from tests.unit.helpers import (
            build_chain_payload,
            build_expiration_map,
            chain_expiry_date,
        )

        strikes = [250.0 + 0.5 * i for i in range(150)]  # 250.0 .. 324.0
        underlying = 287.0
        today = date.today()
        exp_date = chain_expiry_date(30, today=today)

        calls = build_expiration_map(exp_date, "CALL", strikes)
        puts = build_expiration_map(exp_date, "PUT", strikes)
        payload = build_chain_payload(calls, puts, underlying_price=underlying)
        query = OptionChainQuery(symbol="TEST")

        result = build_chain_result(payload, query, today=today)

        assert result["outcome"] == "ok"
        expiration = result["expirations"][0]
        atm = min(strikes, key=lambda s: (abs(s - underlying), s))
        assert expiration["atm_strike"] == atm

        rows = [row["strike"] for row in expiration["strikes"]]
        below = sorted((s for s in strikes if s <= atm), reverse=True)[:50]
        above = sorted(s for s in strikes if s >= atm)[:50]
        expected = sorted(set(below) | set(above))

        # exact expected set, ascending order, and boundary strikes
        assert rows == expected
        assert rows == sorted(rows)
        assert rows[0] == min(expected)
        assert rows[-1] == max(expected)
        # ATM present in the rows (shared by both sides, counted once)
        assert atm in rows
        assert len(rows) == len(below) + len(above) - 1
        assert len(rows) == 99
        assert len(rows) <= 2 * 50

    def test_fewer_strikes_than_max_strikes_returns_all(self) -> None:
        """Only 5 strikes available -> all 5 rows even with ``max_strikes=50``."""
        from schwab_mcp.options_chain import OptionChainQuery, build_chain_result
        from tests.unit.helpers import (
            build_chain_payload,
            build_expiration_map,
            chain_expiry_date,
        )

        strikes = [248.0, 249.0, 250.0, 251.0, 252.0]
        today = date.today()
        exp_date = chain_expiry_date(30, today=today)

        calls = build_expiration_map(exp_date, "CALL", strikes)
        puts = build_expiration_map(exp_date, "PUT", strikes)
        payload = build_chain_payload(calls, puts, underlying_price=250.0)
        query = OptionChainQuery(symbol="TEST")  # max_strikes defaults to 50

        result = build_chain_result(payload, query, today=today)

        assert result["outcome"] == "ok"
        rows = [row["strike"] for row in result["expirations"][0]["strikes"]]
        assert rows == strikes  # all five, ascending
        assert 250.0 in rows  # ATM present
        assert len(rows) == 5
        assert len(rows) <= 2 * 50

    def test_explicit_max_strikes_2_keeps_two_nearest_each_side(self) -> None:
        """``max_strikes=2``: nearest 2 <= ATM union nearest 2 >= ATM.

        Strikes 248..252 step 1, underlying 250 -> {249, 250} union
        {250, 251} = exactly {249, 250, 251}.
        """
        from schwab_mcp.options_chain import OptionChainQuery, build_chain_result
        from tests.unit.helpers import (
            build_chain_payload,
            build_expiration_map,
            chain_expiry_date,
        )

        strikes = [248.0, 249.0, 250.0, 251.0, 252.0]
        today = date.today()
        exp_date = chain_expiry_date(30, today=today)

        calls = build_expiration_map(exp_date, "CALL", strikes)
        puts = build_expiration_map(exp_date, "PUT", strikes)
        payload = build_chain_payload(calls, puts, underlying_price=250.0)
        query = OptionChainQuery(symbol="TEST", max_strikes=2)

        result = build_chain_result(payload, query, today=today)

        assert result["outcome"] == "ok"
        rows = [row["strike"] for row in result["expirations"][0]["strikes"]]
        below = sorted((s for s in strikes if s <= 250.0), reverse=True)[:2]
        above = sorted(s for s in strikes if s >= 250.0)[:2]
        expected = sorted(set(below) | set(above))

        assert rows == expected == [249.0, 250.0, 251.0]
        assert set(rows) == {249.0, 250.0, 251.0}


class TestOptionTypeLegs:
    """``option_type`` controls which StrikeRow leg keys exist (T007).

    ``both`` -> rows carry BOTH ``call`` and ``put`` keys; ``calls`` -> rows
    carry ``call`` only (the ``put`` key must be entirely absent); ``puts`` ->
    rows carry ``put`` only.
    """

    @staticmethod
    def _payload(strikes: list[float], exp_date: str):
        from tests.unit.helpers import build_chain_payload, build_expiration_map

        calls = build_expiration_map(exp_date, "CALL", strikes)
        puts = build_expiration_map(exp_date, "PUT", strikes)
        return build_chain_payload(calls, puts, underlying_price=250.0)

    def test_option_type_both_rows_carry_call_and_put_legs(self) -> None:
        from schwab_mcp.options_chain import OptionChainQuery, build_chain_result
        from tests.unit.helpers import chain_expiry_date

        strikes = [249.0, 250.0, 251.0]
        today = date.today()
        exp_date = chain_expiry_date(30, today=today)
        payload = self._payload(strikes, exp_date)
        query = OptionChainQuery(symbol="TEST", option_type="both")

        result = build_chain_result(payload, query, today=today)

        assert result["outcome"] == "ok"
        rows = result["expirations"][0]["strikes"]
        assert [row["strike"] for row in rows] == strikes
        for row in rows:
            assert "call" in row
            assert "put" in row
            assert isinstance(row["call"], list)
            assert isinstance(row["put"], list)

    def test_option_type_calls_rows_have_call_key_only(self) -> None:
        from schwab_mcp.options_chain import OptionChainQuery, build_chain_result
        from tests.unit.helpers import chain_expiry_date

        strikes = [249.0, 250.0, 251.0]
        today = date.today()
        exp_date = chain_expiry_date(30, today=today)
        payload = self._payload(strikes, exp_date)
        query = OptionChainQuery(symbol="TEST", option_type="calls")

        result = build_chain_result(payload, query, today=today)

        assert result["outcome"] == "ok"
        rows = result["expirations"][0]["strikes"]
        assert [row["strike"] for row in rows] == strikes
        for row in rows:
            assert "call" in row
            assert isinstance(row["call"], list)
            assert "put" not in row  # key entirely absent, not None

    def test_option_type_puts_rows_have_put_key_only(self) -> None:
        from schwab_mcp.options_chain import OptionChainQuery, build_chain_result
        from tests.unit.helpers import chain_expiry_date

        strikes = [249.0, 250.0, 251.0]
        today = date.today()
        exp_date = chain_expiry_date(30, today=today)
        payload = self._payload(strikes, exp_date)
        query = OptionChainQuery(symbol="TEST", option_type="puts")

        result = build_chain_result(payload, query, today=today)

        assert result["outcome"] == "ok"
        rows = result["expirations"][0]["strikes"]
        assert [row["strike"] for row in rows] == strikes
        for row in rows:
            assert "put" in row
            assert isinstance(row["put"], list)
            assert "call" not in row  # key entirely absent, not None


class TestDteFilter:
    """Calendar-day DTE cap of 60 days applies by default (T007, FR-005).

    ``dte_max=None`` does not mean "no cap": the effective cap is 60 and
    expirations with ``dte > 60`` are excluded.
    """

    @staticmethod
    def _payload(exp_dates: list[str], strikes: list[float]):
        from tests.unit.helpers import build_chain_payload, build_expiration_map

        call_map: dict = {}
        put_map: dict = {}
        for exp_date in exp_dates:
            call_map.update(build_expiration_map(exp_date, "CALL", strikes))
            put_map.update(build_expiration_map(exp_date, "PUT", strikes))
        return build_chain_payload(call_map, put_map, underlying_price=250.0)

    def test_default_dte_cap_excludes_expirations_beyond_60_days(self) -> None:
        from schwab_mcp.options_chain import OptionChainQuery, build_chain_result
        from tests.unit.helpers import chain_expiry_date

        today = date.today()
        d7 = chain_expiry_date(7, today=today)
        d30 = chain_expiry_date(30, today=today)
        d70 = chain_expiry_date(70, today=today)
        payload = self._payload([d7, d30, d70], [249.0, 250.0, 251.0])
        query = OptionChainQuery(symbol="TEST")  # dte_max=None -> effective 60

        result = build_chain_result(payload, query, today=today)

        assert result["outcome"] == "ok"
        assert result["filters"]["dte_max_effective"] == 60
        dates = [exp["expiration_date"] for exp in result["expirations"]]
        assert d70 not in dates
        assert set(dates) == {d7, d30}
        assert all(exp["dte"] <= 60 for exp in result["expirations"])
        assert [exp["dte"] for exp in result["expirations"]] == [7, 30]

    def test_expirations_sorted_ascending_by_date(self) -> None:
        from schwab_mcp.options_chain import OptionChainQuery, build_chain_result
        from tests.unit.helpers import chain_expiry_date

        today = date.today()
        d7 = chain_expiry_date(7, today=today)
        d30 = chain_expiry_date(30, today=today)
        # payload maps are built in descending date order on purpose
        payload = self._payload([d30, d7], [249.0, 250.0, 251.0])
        query = OptionChainQuery(symbol="TEST")

        result = build_chain_result(payload, query, today=today)

        assert result["outcome"] == "ok"
        dates = [exp["expiration_date"] for exp in result["expirations"]]
        assert dates == [d7, d30]  # ascending despite insertion order
        for exp in result["expirations"]:
            strikes = [row["strike"] for row in exp["strikes"]]
            assert strikes == sorted(strikes)  # strikes ascending too


# =============================================================================
# Explicit limits (T018, US3) — TDD for quickstart S3.
#
# Covers data-model §3 (strike window per side of the money, DTE filter),
# §4 (``no_expirations_in_range`` structured state) and SC-006 (requested
# limits respected at 100%: zero out-of-bounds contracts).  Selection and
# state shapes follow tmp/008-api-brief.md exactly.
# =============================================================================


class TestExplicitLimits:
    """Explicit ``max_strikes`` and ``dte_max`` limits (US3, T018).

    ``max_strikes=N`` caps the strikes per side of ``atm_strike`` at N
    (ATM shared by both sides -> up to ``2 * N - 1`` rows); ``dte_max``
    sets the effective DTE cap, and when it excludes every expiration the
    result is the structured ``no_expirations_in_range`` state.
    """

    # 41 strikes 230.0 .. 270.0 step 1.0 — wide enough that max_strikes=10
    # trims BOTH sides of the money for an underlying around 250.
    WIDE_STRIKES = [230.0 + 1.0 * i for i in range(41)]

    @staticmethod
    def _payload(exp_dates: list[str], strikes: list[float], underlying: float = 250.0):
        from tests.unit.helpers import build_chain_payload, build_expiration_map

        call_map: dict = {}
        put_map: dict = {}
        for exp_date in exp_dates:
            call_map.update(build_expiration_map(exp_date, "CALL", list(strikes)))
            put_map.update(build_expiration_map(exp_date, "PUT", list(strikes)))
        return build_chain_payload(call_map, put_map, underlying_price=underlying)

    # -- max_strikes=10: <= 10 per side, ATM zone always included -----------

    def test_max_strikes_10_keeps_ten_strikes_per_side_with_exact_window(self) -> None:
        """41-strike ladder, max_strikes=10: nearest 10 <= ATM union nearest
        10 >= ATM, exact boundary strikes, row total <= 2 * 10."""
        from schwab_mcp.options_chain import OptionChainQuery, build_chain_result
        from tests.unit.helpers import chain_expiry_date

        strikes = self.WIDE_STRIKES
        today = date.today()
        exp_date = chain_expiry_date(30, today=today)
        payload = self._payload([exp_date], strikes, underlying=250.0)
        query = OptionChainQuery(symbol="TEST", max_strikes=10)

        result = build_chain_result(payload, query, today=today)

        assert result["outcome"] == "ok"
        expiration = result["expirations"][0]
        atm = expiration["atm_strike"]
        assert atm == 250.0
        rows = [row["strike"] for row in expiration["strikes"]]

        below = sorted((s for s in strikes if s <= atm), reverse=True)[:10]
        above = sorted(s for s in strikes if s >= atm)[:10]
        expected = sorted(set(below) | set(above))
        assert rows == expected

        # exact boundary strikes of the returned window
        assert rows[0] == 241.0
        assert rows[-1] == 259.0
        # <= max_strikes per side of the money (ATM side included)
        assert len([s for s in rows if s <= atm]) <= 10
        assert len([s for s in rows if s >= atm]) <= 10
        assert len(rows) == 19 == len(below) + len(above) - 1  # ATM shared
        assert len(rows) <= 2 * 10

    def test_max_strikes_10_atm_zone_always_included(self) -> None:
        """The ATM strike is always inside the window, even on a midpoint tie
        (ties -> lower strike) between two ladder strikes."""
        from schwab_mcp.options_chain import OptionChainQuery, build_chain_result
        from tests.unit.helpers import chain_expiry_date

        strikes = self.WIDE_STRIKES
        today = date.today()
        exp_date = chain_expiry_date(30, today=today)
        # underlying exactly between 250 and 251 -> tie -> lower strike 250.0
        payload = self._payload([exp_date], strikes, underlying=250.5)
        query = OptionChainQuery(symbol="TEST", max_strikes=10)

        result = build_chain_result(payload, query, today=today)

        expiration = result["expirations"][0]
        atm = expiration["atm_strike"]
        assert atm == 250.0  # tie resolved to the lower strike
        rows = [row["strike"] for row in expiration["strikes"]]
        assert atm in rows, "ATM zone must always be included in the window"
        # the window spans both sides of the money around the ATM strike
        assert any(s < atm for s in rows)
        assert any(s > atm for s in rows)
        assert len(rows) <= 2 * 10

    def test_max_strikes_10_short_side_returns_available_strikes_only(self) -> None:
        """ATM at the top edge of the ladder: the upper side has a single
        strike, and the window holds whatever exists — never invented."""
        from schwab_mcp.options_chain import OptionChainQuery, build_chain_result
        from tests.unit.helpers import chain_expiry_date

        strikes = self.WIDE_STRIKES
        today = date.today()
        exp_date = chain_expiry_date(30, today=today)
        payload = self._payload([exp_date], strikes, underlying=1000.0)
        query = OptionChainQuery(symbol="TEST", max_strikes=10)

        result = build_chain_result(payload, query, today=today)

        expiration = result["expirations"][0]
        atm = expiration["atm_strike"]
        assert atm == 270.0  # closest strike to a far-away underlying
        rows = [row["strike"] for row in expiration["strikes"]]
        assert rows == [261.0, 262.0, 263.0, 264.0, 265.0,
                        266.0, 267.0, 268.0, 269.0, 270.0]
        assert atm in rows
        assert len([s for s in rows if s <= atm]) <= 10
        assert len([s for s in rows if s >= atm]) <= 10
        assert len(rows) <= 2 * 10

    # -- dte_max=120: farther expirations included -------------------------

    def test_dte_max_120_includes_farther_expirations(self) -> None:
        """Expirations at +7/+60/+90/+120/+150 with dte_max=120: dtes include
        90 and 120, exclude 150; the filters echo carries the cap."""
        from schwab_mcp.options_chain import OptionChainQuery, build_chain_result
        from tests.unit.helpers import chain_expiry_date

        today = date.today()
        exp_dates = [chain_expiry_date(d, today=today) for d in (7, 60, 90, 120, 150)]
        payload = self._payload(exp_dates, [249.0, 250.0, 251.0])
        query = OptionChainQuery(symbol="TEST", dte_max=120)

        result = build_chain_result(payload, query, today=today)

        assert result["outcome"] == "ok"
        assert result["filters"]["dte_max_requested"] == 120
        assert result["filters"]["dte_max_effective"] == 120

        expirations = result["expirations"]
        dtes = [exp["dte"] for exp in expirations]
        assert 90 in dtes
        assert 120 in dtes
        assert 150 not in dtes
        assert dtes == [7, 60, 90, 120]  # ascending, +150 excluded
        dates = [exp["expiration_date"] for exp in expirations]
        assert exp_dates[-1] not in dates  # the +150 expiration is gone
        assert all(exp["dte"] <= 120 for exp in expirations)

    # -- dte_max=7 with nearest expiration beyond -> structured state -------

    def test_dte_max_7_nearest_expiration_beyond_yields_structured_state(self) -> None:
        """Nearest expiration at +10 with dte_max=7: structured
        ``no_expirations_in_range`` naming the effective cap, empty
        expirations, and the cap echoed in filters — not a generic error."""
        from schwab_mcp.options_chain import OptionChainQuery, build_chain_result
        from tests.unit.helpers import chain_expiry_date

        today = date.today()
        exp_dates = [chain_expiry_date(d, today=today) for d in (10, 30)]
        payload = self._payload(exp_dates, [249.0, 250.0, 251.0])
        query = OptionChainQuery(symbol="TEST", dte_max=7)

        result = build_chain_result(payload, query, today=today)

        assert result["outcome"] == "no_expirations_in_range"
        assert "dte_max_effective=7" in result["detail"]
        assert result["detail"] == (
            "no_expirations_in_range: dte_max_effective=7 excludes all expirations"
        )
        assert result["expirations"] == []
        assert result["filters"]["dte_max_effective"] == 7
        assert result["filters"]["dte_max_requested"] == 7
