"""Unit tests for negative ``delta_target`` handling and the provider
body-limit fault (bug delta-target-sign-bracketing).

Two layers:

1. Sign defect (offline-provable): ``_delta_bracketed`` and
   ``_select_delta_window`` must operate on ``|delta_target|``.  With the
   raw negative value, bracketing is vacuously false (→ the
   ``strikeCount=200`` ceiling re-fetch runs on EVERY negative-target
   call) and the anchor lands on the deepest-OTM contract — silently
   wrong strikes reported as ``outcome: ok``.
2. Provider body limit (live-provable): the ceiling re-fetch for ``$SPX``
   exceeds Schwab's API-gateway response body limit —
   ``502 {"fault":{"faultstring":"Body buffer overflow","detail":
   {"errorcode":"protocol.http.TooBigBody"}}}`` after ~44 s — which must
   be classified as a deterministic domain error (not transient
   connectivity) and degrade the delta path to the floor payload
   (research R2: closest contracts to the target).

References
----------
- specs/008-extract-option-chain/research.md R2 (graceful degradation)
- docs/tools.md (anchor: "the contract with |delta| closest to the target")
- .specify/bugs/delta-target-sign-bracketing/assessment.md
"""

from __future__ import annotations

from datetime import date

import pytest

from tests.unit.helpers import (
    build_chain_payload,
    build_expiration_map,
    build_response,
    chain_expiry_date,
)

_TODAY = date.today()

_STRIKES = [80.0, 85.0, 90.0, 95.0, 100.0, 105.0, 110.0]

# Put deltas descending as strikes ascend (deeper OTM at lower strikes).
_CALL_DELTAS = [0.95, 0.90, 0.80, 0.65, 0.50, 0.35, 0.20]
_PUT_DELTAS = [-0.05, -0.10, -0.20, -0.30, -0.35, -0.45, -0.60]

_TOOBIG_BODY = {
    "fault": {
        "faultstring": "Body buffer overflow",
        "detail": {"errorcode": "protocol.http.TooBigBody"},
    }
}


def _exp(days_ahead: int = 7) -> str:
    return chain_expiry_date(days_ahead, today=_TODAY)


def _payload(
    strikes: list[float] | None = None,
    call_deltas: list[float] | None = None,
    put_deltas: list[float] | None = None,
) -> dict:
    """One-expiration payload whose CALL/PUT maps share the strike ladder."""
    exp = _exp()
    calls = build_expiration_map(
        exp, "CALL", strikes or _STRIKES, deltas=call_deltas or _CALL_DELTAS
    )
    puts = build_expiration_map(
        exp, "PUT", strikes or _STRIKES, deltas=put_deltas or _PUT_DELTAS
    )
    return build_chain_payload(calls, puts)


class ScriptedClient:
    """Fake schwabdev client returning queued responses in order.

    Records every ``option_chains`` call so tests can assert the refetch
    economy (how many provider requests the delta path made).
    """

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def option_chains(self, symbol, **kwargs):
        self.calls.append({"symbol": symbol, **kwargs})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _query(delta_target: float | None = None, symbol: str = "SPY"):
    from schwab_mcp.options_chain import OptionChainQuery

    query = OptionChainQuery(symbol=symbol, delta_target=delta_target)
    query.validate()
    return query


def _strike_values(result: dict) -> list[float]:
    return [row["strike"] for row in result["expirations"][0]["strikes"]]


# =============================================================================
# Layer A — bracketing must use |delta_target|
# =============================================================================


class TestNegativeDeltaBracketing:
    """``_delta_bracketed`` must compare abs(delta) against |target|."""

    def test_negative_target_straddling_is_bracketed(self) -> None:
        """Deltas −0.20…−0.60 straddle |−0.35| → bracketed (was False)."""
        from schwab_mcp.options_chain import _delta_bracketed

        assert _delta_bracketed(_payload(), _query(-0.35)) is True

    def test_negative_target_all_below_is_not_bracketed(self) -> None:
        """All |delta| < |target| → NOT bracketed → ceiling re-fetch is due."""
        from schwab_mcp.options_chain import _delta_bracketed

        payload = _payload(
            call_deltas=[0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15],
            put_deltas=[-0.02, -0.04, -0.06, -0.08, -0.10, -0.12, -0.15],
        )
        assert _delta_bracketed(payload, _query(-0.35)) is False

    def test_negative_target_all_above_is_not_bracketed(self) -> None:
        """All |delta| > |target| → NOT bracketed."""
        from schwab_mcp.options_chain import _delta_bracketed

        payload = _payload(
            call_deltas=[0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 0.99],
            put_deltas=[-0.40, -0.50, -0.60, -0.70, -0.80, -0.90, -0.99],
        )
        assert _delta_bracketed(payload, _query(-0.35)) is False

    def test_positive_target_straddling_still_bracketed(self) -> None:
        """Positive-target behavior is unchanged (regression guard)."""
        from schwab_mcp.options_chain import _delta_bracketed

        assert _delta_bracketed(_payload(), _query(0.35)) is True


# =============================================================================
# Layer A — anchoring must use |delta_target|
# =============================================================================


class TestNegativeDeltaAnchor:
    """With a negative target the window must center on |delta| ≈ |target|."""

    def test_negative_target_window_centers_on_target_delta(self) -> None:
        """Put |delta| 0.35 sits at strike 100 → window 90…110 (was 80…90)."""
        from schwab_mcp.options_chain import build_chain_result

        result = build_chain_result(_payload(), _query(-0.35))
        assert result["outcome"] == "ok"
        assert _strike_values(result) == [90.0, 95.0, 100.0, 105.0, 110.0]

    def test_negative_target_calls_window_centers_on_target_delta(self) -> None:
        """CALL leg with a negative target: |delta| 0.35 at strike 95."""
        from schwab_mcp.options_chain import build_chain_result

        payload = _payload(
            call_deltas=[0.05, 0.10, 0.20, 0.35, 0.50, 0.65, 0.80],
            put_deltas=[-0.05, -0.10, -0.20, -0.30, -0.35, -0.45, -0.60],
        )
        result = build_chain_result(payload, _query(-0.35, ))
        assert _strike_values(result) == [
            85.0, 90.0, 95.0, 100.0, 105.0, 110.0,
        ]


# =============================================================================
# Layer A — refetch economy: a bracketing floor payload must NOT trigger
# the 200-strike ceiling re-fetch (the request that kills $SPX)
# =============================================================================


class TestRefetchEconomy:
    """A negative-target query that brackets at the floor fetch makes
    exactly ONE provider call."""

    def test_no_ceiling_refetch_when_floor_brackets(self) -> None:
        from schwab_mcp.options_chain import get_option_chain

        client = ScriptedClient([build_response(_payload())])
        result = get_option_chain(client, "SPY", delta_target=-0.35)

        assert result["outcome"] == "ok"
        assert len(client.calls) == 1, (
            "a floor payload that brackets the negative target must not "
            "trigger the strikeCount=200 ceiling re-fetch"
        )
        assert client.calls[0]["strikeCount"] == 100


# =============================================================================
# Layer B — provider body-limit classification
# =============================================================================


class TestBodyLimitClassification:
    """502 + TooBigBody fault → domain error; other 5xx stay transient."""

    def test_502_toobigbody_raises_body_limit_error(self) -> None:
        from schwab_mcp.errors import ConnectivityError
        from schwab_mcp.options_chain import (
            ChainDataError,
            ProviderBodyLimitError,
            fetch_option_chain,
        )

        client = ScriptedClient([build_response(_TOOBIG_BODY, status=502)])
        with pytest.raises(ProviderBodyLimitError) as exc_info:
            fetch_option_chain(client, _query())
        assert isinstance(exc_info.value, ChainDataError)
        assert not isinstance(exc_info.value, ConnectivityError)
        assert "body" in str(exc_info.value).lower()
        assert client.calls[0]["strikeCount"] == 50

    def test_502_without_fault_marker_stays_connectivity_error(self) -> None:
        from schwab_mcp.errors import ConnectivityError
        from schwab_mcp.options_chain import fetch_option_chain

        client = ScriptedClient([build_response({}, status=502)])
        with pytest.raises(ConnectivityError):
            fetch_option_chain(client, _query())


# =============================================================================
# Layer B — graceful degradation of the delta ceiling re-fetch
# =============================================================================


class TestDeltaDegradation:
    """When the ceiling re-fetch hits the body limit, the delta path
    falls back to the floor payload (R2: closest contracts) instead of
    erroring."""

    def test_ceiling_body_limit_falls_back_to_floor_payload(self) -> None:
        from schwab_mcp.options_chain import get_option_chain

        # Floor payload genuinely unbracketed (all |delta| < 0.35) → the
        # ceiling re-fetch is due; the provider rejects it with 502.
        floor = _payload(
            call_deltas=[0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15],
            put_deltas=[-0.02, -0.04, -0.06, -0.08, -0.10, -0.12, -0.15],
        )
        client = ScriptedClient(
            [build_response(floor), build_response(_TOOBIG_BODY, status=502)]
        )
        result = get_option_chain(client, "SPY", delta_target=-0.35)

        assert result["outcome"] == "ok", (
            "the delta path must degrade to the floor payload, not error"
        )
        assert len(client.calls) == 2
        assert client.calls[1]["strikeCount"] == 200

    def test_non_delta_oversized_request_is_actionable_error(self) -> None:
        """An oversized non-delta request surfaces as ChainDataError with
        an actionable message (tool wrapper maps it to ToolError)."""
        from schwab_mcp.options_chain import ChainDataError, get_option_chain

        client = ScriptedClient([build_response(_TOOBIG_BODY, status=502)])
        with pytest.raises(ChainDataError) as exc_info:
            get_option_chain(client, "$SPX", max_strikes=200)
        assert "max_strikes" in str(exc_info.value)