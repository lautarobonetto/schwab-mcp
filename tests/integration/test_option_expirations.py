"""End-to-end integration tests for ``get_option_expiration_chain`` (012).

TDD red-phase suite for tasks.md T004 (extended in T009/T011): the tool does
not exist yet, so every test fails with ``ImportError`` until T007 lands.

The suite runs WITHOUT network and WITHOUT a token: a shared
``FakeExpirationClient`` (``tests.unit.helpers``, T001) records every
``option_expiration_chain`` call and returns a canned payload wrapped in a
real ``requests.Response`` (``tests.unit.helpers.build_response``), exactly
like the ``schwabdev`` client does.

Covers (from tasks.md T004)
---------------------------
- default invocation (symbol only) → exactly ONE provider upcall (SC-004);
- shared outcome envelope: ``symbol``, ``generated_at``, ``outcome: "ok"``,
  ``filters: {dte_max_requested: null, dte_max_effective: 60}``,
  ``expiration_count == len(expirations)``;
- curated-only output — no strikes, quotes, or greek keys anywhere (SC-003);
- provider HTTP 400 → ``outcome: "no_options_listed"``, ``retryable: false``,
  ``expirations: []`` (the live shape found 2026-10-24 in 008, research R6).

References
----------
- specs/012-option-expiration-list/contracts/mcp-tools.md (§2 output, §3 outcomes)
- specs/012-option-expiration-list/data-model.md (§2, §3)
"""

from __future__ import annotations

from datetime import datetime

import pytest

from tests.unit.helpers import (
    FakeExpirationClient,
    build_expiration_chain_payload,
    chain_expiry_date,
)

# Forbidden response keys anywhere in a curated (non-extended) response
# (SC-003: no strikes, quotes, or greeks — data-model.md §2).
FORBIDDEN_CURATED_KEYS = frozenset(
    {
        "strike",
        "strikes",
        "atm_strike",
        "call",
        "put",
        "callExpDateMap",
        "putExpDateMap",
        "bid",
        "ask",
        "last",
        "mark",
        "iv",
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "volume",
        "open_interest",
        "openInterest",
        "theoretical_value",
        "time_value",
        "trade_time",
        "deliverable_note",
        "quote",
        "underlyingPrice",
        "contract_fields",
    }
)


def _payload(extra_days: int = 70) -> dict:
    """Expiration-chain payload with expirations at +7, +30 and +*extra_days*.

    With the default 60-day cap the +*extra_days* expiration is excluded
    when *extra_days* > 60.
    """
    return build_expiration_chain_payload(
        [
            (chain_expiry_date(7), 7, "C"),
            (chain_expiry_date(30), 30, "C"),
            (chain_expiry_date(extra_days), extra_days, "C"),
        ]
    )


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
# Default invocation (quickstart §3 shape)
# =============================================================================


class TestDefaultInvocation:
    """``get_option_expiration_chain(client, 'TEST')`` over a 3-entry fixture."""

    def test_exactly_one_provider_upcall(self) -> None:
        """SC-004: one ``option_expiration_chain`` call per invocation."""
        from schwab_mcp.options_chain import get_option_expiration_chain

        client = FakeExpirationClient(_payload())
        get_option_expiration_chain(client, "TEST")
        assert client.call_count == 1
        assert client.expiration_chain_calls == [{"symbol": "TEST"}]

    def test_shared_result_envelope(self) -> None:
        """The result carries the shared envelope (data-model.md §2)."""
        from schwab_mcp.options_chain import get_option_expiration_chain

        client = FakeExpirationClient(_payload())
        result = get_option_expiration_chain(client, "TEST")

        assert result["symbol"] == "TEST"
        generated = datetime.fromisoformat(result["generated_at"])
        assert generated.tzinfo is not None, "generated_at must be ISO-8601 UTC"
        assert result["outcome"] == "ok"
        assert result["detail"] is None
        assert result["retryable"] is None
        assert result["filters"] == {
            "dte_max_requested": None,
            "dte_max_effective": 60,
        }
        assert result["expiration_count"] == len(result["expirations"])

    def test_curated_output_has_no_strikes_quotes_or_greeks(self) -> None:
        """SC-003: curated-only — zero strike/quote/greek keys anywhere."""
        from schwab_mcp.options_chain import get_option_expiration_chain

        client = FakeExpirationClient(_payload())
        result = get_option_expiration_chain(client, "TEST")

        keys = _collect_keys(result, set())
        offenders = keys & FORBIDDEN_CURATED_KEYS
        assert not offenders, f"non-curated keys leaked into output: {offenders}"
        for entry in result["expirations"]:
            assert set(entry) == {"expiration_date", "dte", "settlement_type"}


# =============================================================================
# no_options_listed — live HTTP 400 shape (research R6)
# =============================================================================


class TestNoOptionsListed400:
    """A provider 400 after validation is the live "no options listed" shape."""

    def test_provider_400_maps_to_no_options_listed(self) -> None:
        from schwab_mcp.options_chain import get_option_expiration_chain

        client = FakeExpirationClient({}, status=400)
        result = get_option_expiration_chain(client, "ZZZZZZ")

        assert result["outcome"] == "no_options_listed"
        assert result["retryable"] is False
        assert result["expirations"] == []
        assert client.call_count == 1


# =============================================================================
# DTE ceiling — end to end (T009, SC-005 semantics mirror)
# =============================================================================


class TestDteCeilingEndToEnd:
    """``dte_max`` filters and echoes exactly like ``get_option_chain``."""

    def test_dte_max_30_filters_and_echoes_the_effective_ceiling(self) -> None:
        from schwab_mcp.options_chain import get_option_expiration_chain

        client = FakeExpirationClient(_payload())
        result = get_option_expiration_chain(client, "TEST", dte_max=30)

        assert result["filters"] == {
            "dte_max_requested": 30,
            "dte_max_effective": 30,
        }
        assert [e["dte"] for e in result["expirations"]] == [7, 30]
        assert all(e["dte"] <= 30 for e in result["expirations"])
        assert client.call_count == 1

    def test_all_expirations_beyond_ceiling_yield_no_expirations_in_range(
        self,
    ) -> None:
        from schwab_mcp.options_chain import get_option_expiration_chain

        payload = build_expiration_chain_payload(
            [
                (chain_expiry_date(40), 40, "C"),
                (chain_expiry_date(70), 70, "C"),
            ]
        )
        client = FakeExpirationClient(payload)
        result = get_option_expiration_chain(client, "TEST", dte_max=30)

        assert result["outcome"] == "no_expirations_in_range"
        assert result["retryable"] is True
        assert result["expirations"] == []
        assert result["expiration_count"] == 0
        # The detail names the effective cap.
        assert "30" in result["detail"]
        assert client.call_count == 1

    def test_default_ceiling_empty_range_names_the_default_cap(self) -> None:
        from schwab_mcp.options_chain import get_option_expiration_chain

        payload = build_expiration_chain_payload(
            [(chain_expiry_date(70), 70, "C")]
        )
        client = FakeExpirationClient(payload)
        result = get_option_expiration_chain(client, "TEST")

        assert result["outcome"] == "no_expirations_in_range"
        assert "60" in result["detail"]
        assert result["expiration_count"] == 0
        assert client.call_count == 1


# =============================================================================
# extended=true — raw provider passthrough (T011, US3 — contract §1)
# =============================================================================


class TestExtendedPassthrough:
    """``extended=True`` adds the exact raw provider payload (C-09 pattern)."""

    def test_extended_adds_the_unchanged_provider_payload(self) -> None:
        import copy

        from schwab_mcp.options_chain import get_option_expiration_chain

        payload = _payload()
        snapshot = copy.deepcopy(payload)
        client = FakeExpirationClient(payload)
        result = get_option_expiration_chain(client, "TEST", extended=True)

        assert result["provider"] == snapshot
        assert result["outcome"] == "ok"
        for key in (
            "symbol",
            "generated_at",
            "outcome",
            "filters",
            "expirations",
            "expiration_count",
        ):
            assert key in result, f"curated field {key} missing on extended result"

    def test_default_has_no_provider_key(self) -> None:
        from schwab_mcp.options_chain import get_option_expiration_chain

        client = FakeExpirationClient(_payload())
        result = get_option_expiration_chain(client, "TEST")

        assert "provider" not in result
        assert result["outcome"] == "ok"

    def test_extended_on_non_ok_outcome_still_carries_curated_fields(self) -> None:
        from schwab_mcp.options_chain import get_option_expiration_chain

        payload = {"status": None, "expirationList": []}
        client = FakeExpirationClient(payload)
        result = get_option_expiration_chain(client, "TEST", extended=True)

        assert result["provider"] == payload
        assert result["outcome"] == "no_options_listed"
        assert result["expirations"] == []
        assert result["symbol"] == "TEST"


# =============================================================================
# Shared error taxonomy (T005 — research R6, mirrored 008 semantics)
# =============================================================================


class TestProviderFailureTaxonomy:
    """Provider failures surface as the shared taxonomy, never a partial
    result — exactly one upstream call and a failure audit event."""

    @pytest.mark.parametrize("status", [500, 408, 429], ids=["500", "408", "429"])
    def test_transient_status_raises_connectivity_error(self, status) -> None:
        from schwab_mcp.errors import ConnectivityError
        from schwab_mcp.options_chain import get_option_expiration_chain

        client = FakeExpirationClient({}, status=status)
        with pytest.raises(ConnectivityError) as excinfo:
            get_option_expiration_chain(client, "TEST")

        message = str(excinfo.value)
        assert "Check connectivity" in message or "unreachable" in message
        assert excinfo.value.__cause__ is not None
        assert client.call_count == 1

    @pytest.mark.parametrize("status", [500, 408, 429], ids=["500", "408", "429"])
    def test_transient_status_emits_failure_audit_event(self, status, capsys) -> None:
        from schwab_mcp.errors import ConnectivityError
        from schwab_mcp.options_chain import get_option_expiration_chain

        client = FakeExpirationClient({}, status=status)
        with pytest.raises(ConnectivityError):
            get_option_expiration_chain(client, "TEST")

        stderr = capsys.readouterr().err
        assert "expiration_chain_query_failure" in stderr
        assert "transient" in stderr
        assert "provider_unreachable" in stderr

    def test_http_401_keeps_reauth_taxonomy_as_cause(self) -> None:
        """The 401 taxonomy error is preserved as ``__cause__`` of the
        wrapping ``ConnectivityError`` (008-identical behaviour)."""
        from schwab_mcp.errors import (
            ConnectivityError,
            ReauthorizationRequiredError,
        )
        from schwab_mcp.options_chain import get_option_expiration_chain

        client = FakeExpirationClient({}, status=401)
        with pytest.raises(ConnectivityError) as excinfo:
            get_option_expiration_chain(client, "TEST")
        assert isinstance(excinfo.value.__cause__, ReauthorizationRequiredError)
        assert client.call_count == 1

    def test_raising_client_surfaces_connectivity_error(self) -> None:
        from schwab_mcp.errors import ConnectivityError
        from schwab_mcp.options_chain import get_option_expiration_chain

        client = FakeExpirationClient(error=OSError("network down"))
        with pytest.raises(ConnectivityError):
            get_option_expiration_chain(client, "TEST")
        assert client.call_count == 1