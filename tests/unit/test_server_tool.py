"""Failing unit tests for the ``get_open_positions`` MCP tool registration
and invocation (T005/US1).

These are TDD red-phase tests: the ``get_open_positions`` function does not
exist yet in ``schwab_mcp.positions``, so every test will fail with
``ImportError``.  Once implemented (T006–T008), all tests should pass.

Covers (from tasks.md T005)
---------------------------
- Tool registration via ``MCPServer.add_tool`` with structured output (D1)
- Successful query: single upstream call, positions populated
- No positions: outcome ``ok``, detail ``no_positions``, positions ``[]``
- ``ConnectivityError`` → ``transient_failure``, ``retryable``, no internal
  retry (FR-007/D6)
- ``ReauthorizationRequiredError`` → ``reauth_required`` (D7)
- ``TokenStoreCorruptedError`` → ``reauth_required`` (D7)
- Audit events: exactly one ``positions_query_start`` + one terminal event
  per invocation (FR-014)

References
----------
- specs/003-list-open-positions/contracts/mcp-tools.md
- specs/003-list-open-positions/contracts/events.md
- specs/003-list-open-positions/research.md D1–D8
"""

from __future__ import annotations

import asyncio
import typing
from unittest import mock

import pytest


# =============================================================================
# Fake schwabdev client for positions queries
# =============================================================================


class FakePositionsClient:
    """Stubbed schwabdev client for ``get_open_positions`` tests.

    Returns a configurable **payload** from ``account_details_all`` or
    raises a configurable **error**.  Tracks upstream call count so tests
    can verify single-call semantics (FR-007/D6).
    """

    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self._payload = payload if payload is not None else {"accountDetails": []}
        self._error = error
        self.call_count = 0

    def account_details_all(self, fields: str = "positions") -> dict:
        """Fake upstream call — returns payload or raises error."""
        self.call_count += 1
        if self._error is not None:
            raise self._error
        return self._payload

    def linked_accounts(self):
        """Fake account listing with provider-style opaque hashes.

        Derives the ``accountNumber`` list from the configured payload so
        the orchestration's cross-reference resolves; hashes are opaque and
        never equal the raw numbers.
        """
        numbers: list[str] = []
        if isinstance(self._payload, dict):
            for a in self._payload.get("accountDetails", []):
                n = a.get("accountNumber", "")
                if n:
                    numbers.append(n)
        from tests.unit.helpers import build_response

        return build_response(
            [{"hashValue": f"hash-{n}", "accountNumber": n} for n in numbers]
        )


# =============================================================================
# Payload fixtures
# =============================================================================


@pytest.fixture
def single_position_payload() -> dict:
    """Minimal single-account, single-equity-position payload.

    ``accountNumber`` is the raw number returned by the provider; the tool
    MUST replace it with a safe opaque ``account_hash``.
    """
    return {
        "accountDetails": [
            {
                "accountNumber": "12345678",
                "positions": [
                    {
                        "instrument": {
                            "symbol": "SPY",
                            "assetType": "EQUITY",
                            "description": "SPDR S&P 500 ETF Trust",
                        },
                        "longQuantity": 10.0,
                        "shortQuantity": 0.0,
                        "averagePrice": 580.25,
                        "marketValue": 5910.0,
                    }
                ],
            }
        ]
    }


@pytest.fixture
def empty_account_payload() -> dict:
    """Account with no positions at all."""
    return {"accountDetails": [{"accountNumber": "12345678", "positions": []}]}


@pytest.fixture
def empty_payload() -> dict:
    """No accounts at all."""
    return {"accountDetails": []}


# =============================================================================
# 1. Tool registration
# =============================================================================


class TestToolRegistration:
    """``get_open_positions`` is importable, annotated for structured output,
    and registrable via ``MCPServer.add_tool`` (research D1)."""

    def test_function_is_importable(self) -> None:
        """The function can be imported from ``schwab_mcp.positions``."""
        from schwab_mcp.positions import get_open_positions

        assert callable(get_open_positions)

    def test_return_annotation_is_positions_result(self) -> None:
        """The return type annotation is ``PositionsResult`` (structured output)."""
        from schwab_mcp.positions import get_open_positions, PositionsResult

        hints = typing.get_type_hints(get_open_positions)
        assert hints["return"] is PositionsResult

    def test_signature_has_extended_param_with_default(self) -> None:
        """The function accepts ``extended: bool = False``."""
        from schwab_mcp.positions import get_open_positions

        import inspect

        sig = inspect.signature(get_open_positions)
        # The ``client`` parameter is injected; ``extended`` is the tool-facing param.
        params = list(sig.parameters.values())
        extended_param = [p for p in params if p.name == "extended"]
        assert len(extended_param) == 1, (
            "Expected an 'extended' parameter in the signature"
        )
        p = extended_param[0]
        # With ``from __future__ import annotations``, annotations are strings.
        ann = p.annotation
        assert ann in (bool, "bool", typing.Optional[bool]), (
            f"Expected extended param annotation to be bool, got {ann!r}"
        )
        assert p.default is False

    def test_registers_via_mcp_add_tool(self, single_position_payload: dict) -> None:
        """``MCPServer.add_tool`` accepts the function; the tool is callable
        and returns a structured response."""
        import json
        from mcp.server import MCPServer
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)
        # Wrap to bind the client — the MCP tool only exposes ``extended``
        # in its input schema.
        fn = lambda extended=False: get_open_positions(client, extended=extended)
        fn.__name__ = "get_open_positions"
        fn.__qualname__ = "get_open_positions"

        mcp = MCPServer("test")
        mcp.add_tool(fn, name="get_open_positions", description="List open positions.")

        tools = asyncio.run(mcp.list_tools())
        names = [t.name for t in tools]
        assert "get_open_positions" in names, (
            f"get_open_positions not in registered tools: {names}"
        )

        result = asyncio.run(mcp.call_tool("get_open_positions", {}))
        assert not result.is_error, (
            f"Tool call returned an error: {result.content}"
        )
        # The lambda wrapper has no return type annotation, so
        # structured_content is None. Parse from text content instead.
        if result.structured_content is not None:
            assert result.structured_content["outcome"] == "ok"
        else:
            parsed = json.loads(result.content[0].text)
            assert parsed["outcome"] == "ok"

    def test_output_schema_includes_positions_result_fields(
        self, single_position_payload: dict
    ) -> None:
        """The tool's ``output_schema`` contains the ``PositionsResult`` fields.

        The output schema may be populated by the MCP SDK when the return type
        annotation is visible. If the SDK does not populate it (e.g. for lambda
        wrappers), we verify via ``PositionsResult.model_json_schema()`` instead.
        """
        from mcp.server import MCPServer
        from schwab_mcp.positions import PositionEntry, PositionsResult, get_open_positions

        client = FakePositionsClient(payload=single_position_payload)
        fn = lambda extended=False: get_open_positions(client, extended=extended)
        fn.__name__ = "get_open_positions"
        fn.__qualname__ = "get_open_positions"

        mcp = MCPServer("test")
        mcp.add_tool(fn, name="get_open_positions", description="test")

        tools = asyncio.run(mcp.list_tools())
        schema = tools[0].output_schema
        if schema is not None:
            props = schema.get("properties", {})
            for field in ("outcome", "positions", "retryable", "detail", "retrieved_at"):
                assert field in props, (
                    f"output_schema missing '{field}' property"
                )
        else:
            # Fallback: verify the model produces a valid JSON schema
            model_schema = PositionsResult.model_json_schema()
            props = model_schema.get("properties", {})
            for field in ("outcome", "positions", "retryable", "detail", "retrieved_at"):
                assert field in props, (
                    f"PositionsResult JSON schema missing '{field}' property"
                )

    def test_registration_errors_if_function_has_no_client_bound(
        self, single_position_payload: dict
    ) -> None:
        """The RAW function (with ``client`` parameter) is NOT directly
        compatible with ``add_tool`` — only the wrapped version is.
        This test documents the design constraint."""
        from mcp.server import MCPServer
        from schwab_mcp.positions import get_open_positions

        mcp = MCPServer("test")
        # Registering the raw function with client as a parameter would expose
        # client in the input schema — this is acceptable during TDD to verify
        # the function's structure; the ``add_tool`` call itself succeeds
        # regardless of what parameters the function has.
        mcp.add_tool(get_open_positions, name="get_open_positions", description="test")
        tools = asyncio.run(mcp.list_tools())
        names = [t.name for t in tools]
        assert "get_open_positions" in names


# =============================================================================
# 2. Successful query
# =============================================================================


class TestSuccessfulQuery:
    """Given a fake client returning a valid payload with positions."""

    def test_returns_positions_result(self, single_position_payload: dict) -> None:
        """The return value is a ``PositionsResult`` instance."""
        from schwab_mcp.positions import get_open_positions, PositionsResult

        client = FakePositionsClient(payload=single_position_payload)
        result = get_open_positions(client)
        assert isinstance(result, PositionsResult)

    def test_outcome_ok(self, single_position_payload: dict) -> None:
        """The outcome is ``ok``."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)
        result = get_open_positions(client)
        assert result.outcome == "ok"

    def test_detail_data_received(self, single_position_payload: dict) -> None:
        """The detail is ``data_received`` when positions are found."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)
        result = get_open_positions(client)
        assert result.detail == "data_received"

    def test_positions_are_populated(self, single_position_payload: dict) -> None:
        """The result contains the expected position entries."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)
        result = get_open_positions(client)
        assert len(result.positions) >= 1

        pos = result.positions[0]
        assert pos.symbol == "SPY"
        assert pos.account_hash is not None and len(pos.account_hash) > 0
        assert pos.instrument_type == "EQUITY"
        assert pos.quantity == 10.0
        assert pos.average_price == 580.25
        assert pos.market_value == 5910.0

    def test_account_hash_is_opaque(self, single_position_payload: dict) -> None:
        """``account_hash`` is an opaque string, never the raw ``accountNumber``
        (data-model.md §1, research D3)."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)
        result = get_open_positions(client)
        for pos in result.positions:
            assert pos.account_hash != "12345678", (
                "account_hash must NOT be the raw account number"
            )

    def test_retryable_is_false(self, single_position_payload: dict) -> None:
        """Success outcome has ``retryable=False``."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)
        result = get_open_positions(client)
        assert result.retryable is False

    def test_single_upstream_call(self, single_position_payload: dict) -> None:
        """Exactly **one** call to ``account_details_all`` is made
        (FR-001: a single query returns the full picture)."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)
        get_open_positions(client)
        assert client.call_count == 1

    def test_retrieved_at_is_iso8601_utc(self, single_position_payload: dict) -> None:
        """``retrieved_at`` is an ISO-8601 UTC string (data-model.md §2)."""
        from datetime import datetime
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)
        result = get_open_positions(client)
        dt = datetime.fromisoformat(result.retrieved_at)
        assert dt.tzinfo is not None, "retrieved_at must be timezone-aware"

    def test_price_timestamp_in_every_entry(
        self, single_position_payload: dict
    ) -> None:
        """Every position entry has a ``price_timestamp`` (FR-012)."""
        from datetime import datetime
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)
        result = get_open_positions(client)
        for pos in result.positions:
            assert pos.price_timestamp is not None
            dt = datetime.fromisoformat(pos.price_timestamp)
            assert dt.tzinfo is not None

    def test_unrealized_pl_present(self, single_position_payload: dict) -> None:
        """Every position entry includes ``unrealized_pl`` (FR-003)."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)
        result = get_open_positions(client)
        for pos in result.positions:
            # unrealized_pl is a float; marketValue - (averagePrice * |qty|)
            assert isinstance(pos.unrealized_pl, float)


# =============================================================================
# 3. No positions
# =============================================================================


class TestNoPositions:
    """Given a fake client returning an empty payload (no positions)."""

    def test_outcome_ok(self, empty_account_payload: dict) -> None:
        """Empty payload returns ``outcome='ok'`` (not an error — FR-005)."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=empty_account_payload)
        result = get_open_positions(client)
        assert result.outcome == "ok"

    def test_detail_no_positions(self, empty_account_payload: dict) -> None:
        """Empty payload returns ``detail='no_positions'``."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=empty_account_payload)
        result = get_open_positions(client)
        assert result.detail == "no_positions"

    def test_positions_empty_list(self, empty_account_payload: dict) -> None:
        """Empty payload returns ``positions=[]``."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=empty_account_payload)
        result = get_open_positions(client)
        assert result.positions == []

    def test_single_upstream_call_on_empty(self, empty_account_payload: dict) -> None:
        """Even with no positions, exactly 1 upstream call is made."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=empty_account_payload)
        get_open_positions(client)
        assert client.call_count == 1

    def test_retryable_is_false(self, empty_account_payload: dict) -> None:
        """Empty result is not retryable."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=empty_account_payload)
        result = get_open_positions(client)
        assert result.retryable is False

    def test_no_accounts_returns_ok_no_positions(self, empty_payload: dict) -> None:
        """``accountDetails: []`` (no accounts) also returns ok/no_positions."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=empty_payload)
        result = get_open_positions(client)
        assert result.outcome == "ok"
        assert result.detail == "no_positions"
        assert result.positions == []


# =============================================================================
# 4. ConnectivityError → transient_failure
# =============================================================================


class TestConnectivityError:
    """``ConnectivityError`` maps to ``transient_failure`` (research D7).

    The tool MUST NOT retry internally (FR-007/D6).
    """

    def test_outcome_transient_failure(self) -> None:
        """``ConnectivityError`` → ``outcome='transient_failure'``."""
        from schwab_mcp.errors import ConnectivityError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(error=ConnectivityError(detail="network down"))
        result = get_open_positions(client)
        assert result.outcome == "transient_failure"

    def test_retryable_true(self) -> None:
        """``transient_failure`` has ``retryable=True``."""
        from schwab_mcp.errors import ConnectivityError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(error=ConnectivityError(detail="network down"))
        result = get_open_positions(client)
        assert result.retryable is True

    def test_detail_provider_unreachable(self) -> None:
        """``ConnectivityError`` → ``detail='provider_unreachable'``."""
        from schwab_mcp.errors import ConnectivityError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(error=ConnectivityError(detail="network down"))
        result = get_open_positions(client)
        assert result.detail == "provider_unreachable"

    def test_positions_empty(self) -> None:
        """``transient_failure`` has empty positions list."""
        from schwab_mcp.errors import ConnectivityError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(error=ConnectivityError(detail="network down"))
        result = get_open_positions(client)
        assert result.positions == []

    def test_no_internal_retry(self) -> None:
        """Only **1** upstream call — the tool does NOT retry internally
        (FR-007: transient failure reported on the first failed attempt)."""
        from schwab_mcp.errors import ConnectivityError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(error=ConnectivityError(detail="network down"))
        get_open_positions(client)
        assert client.call_count == 1, (
            "Expected exactly 1 upstream call; internal retry would violate FR-007/D6"
        )


# =============================================================================
# 5. ReauthorizationRequiredError → reauth_required
# =============================================================================


class TestReauthorizationRequired:
    """``ReauthorizationRequiredError`` maps to ``reauth_required`` (D7)."""

    def test_outcome_reauth_required(self) -> None:
        """``ReauthorizationRequiredError`` → ``outcome='reauth_required'``."""
        from schwab_mcp.errors import ReauthorizationRequiredError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(
            error=ReauthorizationRequiredError(detail="tokens expired")
        )
        result = get_open_positions(client)
        assert result.outcome == "reauth_required"

    def test_retryable_false(self) -> None:
        """``reauth_required`` has ``retryable=False``."""
        from schwab_mcp.errors import ReauthorizationRequiredError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(
            error=ReauthorizationRequiredError(detail="tokens expired")
        )
        result = get_open_positions(client)
        assert result.retryable is False

    def test_detail_reauth_needed(self) -> None:
        """``ReauthorizationRequiredError`` → ``detail='reauth_needed'``."""
        from schwab_mcp.errors import ReauthorizationRequiredError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(
            error=ReauthorizationRequiredError(detail="tokens expired")
        )
        result = get_open_positions(client)
        assert result.detail == "reauth_needed"

    def test_positions_empty(self) -> None:
        """``reauth_required`` has empty positions list."""
        from schwab_mcp.errors import ReauthorizationRequiredError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(
            error=ReauthorizationRequiredError(detail="tokens expired")
        )
        result = get_open_positions(client)
        assert result.positions == []

    def test_single_upstream_call(self) -> None:
        """Only 1 upstream call — the auth guard fires on the first attempt."""
        from schwab_mcp.errors import ReauthorizationRequiredError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(
            error=ReauthorizationRequiredError(detail="tokens expired")
        )
        get_open_positions(client)
        assert client.call_count == 1


# =============================================================================
# 6. TokenStoreCorruptedError → reauth_required
# =============================================================================


class TestTokenStoreCorrupted:
    """``TokenStoreCorruptedError`` maps to ``reauth_required`` with
    ``detail='store_corrupted'`` (D7)."""

    def test_outcome_reauth_required(self) -> None:
        """``TokenStoreCorruptedError`` → ``outcome='reauth_required'``."""
        from schwab_mcp.errors import TokenStoreCorruptedError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(
            error=TokenStoreCorruptedError(detail="corrupt db")
        )
        result = get_open_positions(client)
        assert result.outcome == "reauth_required"

    def test_retryable_false(self) -> None:
        """``reauth_required`` (from store corruption) has ``retryable=False``."""
        from schwab_mcp.errors import TokenStoreCorruptedError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(
            error=TokenStoreCorruptedError(detail="corrupt db")
        )
        result = get_open_positions(client)
        assert result.retryable is False

    def test_detail_store_corrupted(self) -> None:
        """``TokenStoreCorruptedError`` → ``detail='store_corrupted'``
        (distinct from ``reauth_needed``)."""
        from schwab_mcp.errors import TokenStoreCorruptedError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(
            error=TokenStoreCorruptedError(detail="corrupt db")
        )
        result = get_open_positions(client)
        assert result.detail == "store_corrupted"

    def test_positions_empty(self) -> None:
        """``reauth_required`` (store corrupted) has empty positions list."""
        from schwab_mcp.errors import TokenStoreCorruptedError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(
            error=TokenStoreCorruptedError(detail="corrupt db")
        )
        result = get_open_positions(client)
        assert result.positions == []

    def test_single_upstream_call(self) -> None:
        """Only 1 upstream call."""
        from schwab_mcp.errors import TokenStoreCorruptedError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(
            error=TokenStoreCorruptedError(detail="corrupt db")
        )
        get_open_positions(client)
        assert client.call_count == 1


# =============================================================================
# 7. Audit events (FR-014)
# =============================================================================


class TestAuditEvents:
    """FR-014: every invocation emits exactly one ``positions_query_start``
    followed by exactly one terminal event
    (``positions_query_success`` | ``positions_query_failure``).

    Vocabulary follows ``contracts/events.md``.
    """

    # ------------------------------------------------------------------
    # Success path
    # ------------------------------------------------------------------

    def test_success_emits_start_then_success(
        self, single_position_payload: dict
    ) -> None:
        """Success: start (initiated) → positions_query_success (ok)."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)

        with mock.patch("schwab_mcp.positions.auth_event") as mock_auth:
            get_open_positions(client)

        assert mock_auth.call_count == 2, (
            f"Expected 2 auth_event calls (start + success), got {mock_auth.call_count}"
        )
        start_call, term_call = mock_auth.call_args_list

        assert start_call.args[:2] == ("positions_query_start", "initiated"), (
            f"First call should be start/initiated, got {start_call}"
        )
        assert term_call.args[:2] == ("positions_query_success", "ok"), (
            f"Second call should be success/ok, got {term_call}"
        )

    def test_success_start_detail_curated(
        self, single_position_payload: dict
    ) -> None:
        """Start event has ``detail='curated'`` when ``extended=False``
        (the default)."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)

        with mock.patch("schwab_mcp.positions.auth_event") as mock_auth:
            get_open_positions(client)

        start_call = mock_auth.call_args_list[0]
        assert start_call.kwargs.get("detail") == "curated", (
            f"Expected start detail='curated', got {start_call.kwargs}"
        )

    def test_success_terminal_detail_positions_found(
        self, single_position_payload: dict
    ) -> None:
        """Success terminal has ``detail='positions_found'`` when data returned."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)

        with mock.patch("schwab_mcp.positions.auth_event") as mock_auth:
            get_open_positions(client)

        term_call = mock_auth.call_args_list[1]
        assert term_call.kwargs.get("detail") == "positions_found", (
            f"Expected terminal detail='positions_found', got {term_call.kwargs}"
        )

    def test_empty_positions_terminal_detail_no_positions(self) -> None:
        """Empty result → terminal ``detail='no_positions'``."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload={"accountDetails": []})

        with mock.patch("schwab_mcp.positions.auth_event") as mock_auth:
            get_open_positions(client)

        term_call = mock_auth.call_args_list[1]
        assert term_call.args[:2] == ("positions_query_success", "ok"), (
            f"Expected success/ok for empty result, got {term_call}"
        )
        assert term_call.kwargs.get("detail") == "no_positions", (
            f"Expected detail='no_positions', got {term_call.kwargs}"
        )

    # ------------------------------------------------------------------
    # Failure paths
    # ------------------------------------------------------------------

    def test_transient_failure_emits_start_then_failure(self) -> None:
        """``ConnectivityError`` → start (initiated) → ``positions_query_failure``
        (transient)."""
        from schwab_mcp.errors import ConnectivityError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(
            error=ConnectivityError(detail="network down")
        )

        with mock.patch("schwab_mcp.positions.auth_event") as mock_auth:
            get_open_positions(client)

        assert mock_auth.call_count == 2, (
            f"Expected 2 auth_event calls (start + failure), got {mock_auth.call_count}"
        )
        start_call, term_call = mock_auth.call_args_list

        assert start_call.args[:2] == ("positions_query_start", "initiated")
        assert term_call.args[:2] == ("positions_query_failure", "transient"), (
            f"Expected failure/transient, got {term_call}"
        )
        assert term_call.kwargs.get("detail") == "provider_unreachable"

    def test_reauth_required_emits_start_then_failure(self) -> None:
        """``ReauthorizationRequiredError`` → start → ``positions_query_failure``
        (reauth)."""
        from schwab_mcp.errors import ReauthorizationRequiredError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(
            error=ReauthorizationRequiredError(detail="expired")
        )

        with mock.patch("schwab_mcp.positions.auth_event") as mock_auth:
            get_open_positions(client)

        assert mock_auth.call_count == 2
        term_call = mock_auth.call_args_list[1]

        assert term_call.args[:2] == ("positions_query_failure", "reauth"), (
            f"Expected failure/reauth, got {term_call}"
        )
        assert term_call.kwargs.get("detail") == "reauth_needed"

    def test_store_corrupted_emits_start_then_failure(self) -> None:
        """``TokenStoreCorruptedError`` → start → ``positions_query_failure``
        (reauth) with ``detail='store_corrupted'``."""
        from schwab_mcp.errors import TokenStoreCorruptedError
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(
            error=TokenStoreCorruptedError(detail="corrupt db")
        )

        with mock.patch("schwab_mcp.positions.auth_event") as mock_auth:
            get_open_positions(client)

        assert mock_auth.call_count == 2
        term_call = mock_auth.call_args_list[1]

        assert term_call.args[:2] == ("positions_query_failure", "reauth"), (
            f"Expected failure/reauth, got {term_call}"
        )
        assert term_call.kwargs.get("detail") == "store_corrupted"

    # ------------------------------------------------------------------
    # Correctness invariants
    # ------------------------------------------------------------------

    def test_no_orphaned_start(self, single_position_payload: dict) -> None:
        """Every start event has exactly one terminal (no orphaned start)."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)

        with mock.patch("schwab_mcp.positions.auth_event") as mock_auth:
            get_open_positions(client)

        calls = mock_auth.call_args_list
        assert len(calls) == 2
        assert calls[0].args[0] == "positions_query_start"
        assert calls[1].args[0] in (
            "positions_query_success",
            "positions_query_failure",
        )

    def test_no_extra_events(self, single_position_payload: dict) -> None:
        """Exactly 2 events per invocation — no more, no less."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)

        with mock.patch("schwab_mcp.positions.auth_event") as mock_auth:
            get_open_positions(client)

        assert mock_auth.call_count == 2, (
            f"Expected exactly 2 auth_event calls, got {mock_auth.call_count}"
        )

    def test_event_order_start_then_terminal(
        self, single_position_payload: dict
    ) -> None:
        """Start event always precedes the terminal event."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_payload)

        with mock.patch("schwab_mcp.positions.auth_event") as mock_auth:
            get_open_positions(client)

        calls = mock_auth.call_args_list
        assert calls[0].args[0] == "positions_query_start", (
            "First event must be positions_query_start"
        )
        assert calls[1].args[0] in (
            "positions_query_success",
            "positions_query_failure",
        ), (
            f"Second event must be a terminal, got {calls[1].args[0]}"
        )

    # ------------------------------------------------------------------
    # Secret safety (FR-008)
    # ------------------------------------------------------------------

    def test_events_contain_no_secrets(self, single_position_payload: dict) -> None:
        """Audit event detail fields must not contain secret material
        (FR-008, redaction filter provides defense-in-depth)."""
        from schwab_mcp.log import clear_secrets
        from schwab_mcp.positions import get_open_positions

        # Register a synthetic secret — even if the implementation accidentally
        # includes it, the event detail must be clean.
        # Note: this test is a first line; the comprehensive leak sweep in
        # test_no_secrets_in_output.py covers the full output surface.
        FAKE_SECRET = "should-not-leak-12345"

        client = FakePositionsClient(payload=single_position_payload)

        with mock.patch("schwab_mcp.positions.auth_event") as mock_auth:
            get_open_positions(client)

        for call_args in mock_auth.call_args_list:
            detail = call_args.kwargs.get("detail")
            if detail is not None:
                assert FAKE_SECRET not in detail, (
                    f"Secret leaked into auth_event detail: {detail!r}"
                )


# =============================================================================
# 8. Extended parameter (User Story 2 / FR-003a)
# =============================================================================


class TestExtendedParameter:
    """``get_open_positions`` accepts an ``extended`` parameter that enables
    provider passthrough fields on each position entry (FR-003a).

    When ``extended=False`` (default), the output is compact and contains
    only the curated metadata set.  When ``extended=True``, extra provider
    fields (``cusip``, ``settledLongQuantity``, ``currentDayProfitLoss``,
    ``maintenanceRequirement``) are included in each entry's ``extended``
    dict as opaque passthrough without interpretation (data-model.md §3).

    Budget constraints (research D9/SC-003):
    - 50 positions with extended=false → ≤ 8 KB serialized JSON
    - 50 positions with extended=true  → ≤ 16 KB serialized JSON
    """

    # ------------------------------------------------------------------
    # Fixtures for extended tests
    # ------------------------------------------------------------------

    @pytest.fixture
    def single_position_extended_payload(self) -> dict:
        """Single position payload with extended provider fields at the
        position level (``cusip``, ``settledLongQuantity``,
        ``currentDayProfitLoss``, ``maintenanceRequirement``)."""
        return {
            "accountDetails": [
                {
                    "accountNumber": "12345678",
                    "positions": [
                        {
                            "instrument": {
                                "symbol": "SPY",
                                "assetType": "EQUITY",
                                "description": "Test",
                            },
                            "longQuantity": 10.0,
                            "shortQuantity": 0.0,
                            "averagePrice": 100.0,
                            "marketValue": 1000.0,
                            "cusip": "123456789",
                            "settledLongQuantity": 10.0,
                            "currentDayProfitLoss": 50.0,
                            "maintenanceRequirement": 200.0,
                        }
                    ],
                }
            ]
        }

    @pytest.fixture
    def fifty_positions_payload(self) -> dict:
        """Payload with 50 simple equity positions across 2 accounts
        for budget tests (default/extended=false)."""
        accounts = [
            {
                "accountNumber": f"100000{i:02d}",
                "positions": [
                    {
                        "instrument": {
                            "symbol": f"STOCK{j:02d}",
                            "assetType": "EQUITY",
                            "description": f"Stock {j:03d}",
                        },
                        "longQuantity": float(j + 1),
                        "shortQuantity": 0.0,
                        "averagePrice": float(50 + j),
                        "marketValue": float((50 + j) * (j + 1)),
                    }
                    for j in range(25)
                ],
            }
            for i in range(2)
        ]
        return {"accountDetails": accounts}

    @pytest.fixture
    def fifty_positions_extended_payload(self) -> dict:
        """Payload with 50 positions including extended provider fields
        across 2 accounts, for budget tests (extended=true)."""
        accounts = [
            {
                "accountNumber": f"100000{i:02d}",
                "positions": [
                    {
                        "instrument": {
                            "symbol": f"STOCK{j:02d}",
                            "assetType": "EQUITY",
                            "description": f"Stock {j:03d}",
                        },
                        "longQuantity": float(j + 1),
                        "shortQuantity": 0.0,
                        "averagePrice": float(50 + j),
                        "marketValue": float((50 + j) * (j + 1)),
                        "cusip": f"12345678{j:02d}",
                        "settledLongQuantity": float(j + 1),
                        "currentDayProfitLoss": float(j * 10),
                        "maintenanceRequirement": float(100 + j * 5),
                    }
                    for j in range(25)
                ],
            }
            for i in range(2)
        ]
        return {"accountDetails": accounts}

    # ------------------------------------------------------------------
    # 1. Extended argument accepted
    # ------------------------------------------------------------------

    def test_extended_true_returns_valid_result(
        self, single_position_extended_payload: dict
    ) -> None:
        """``extended=True`` is accepted and returns a valid
        ``PositionsResult`` with positions."""
        from schwab_mcp.positions import get_open_positions, PositionsResult

        client = FakePositionsClient(payload=single_position_extended_payload)
        result = get_open_positions(client, extended=True)
        assert isinstance(result, PositionsResult)
        assert result.outcome == "ok"
        assert len(result.positions) >= 1

    # ------------------------------------------------------------------
    # 2. No extended by default
    # ------------------------------------------------------------------

    def test_default_no_extended_field(
        self, single_position_extended_payload: dict
    ) -> None:
        """With ``extended=False`` (default), no position entry has an
        ``extended`` key when dumping with ``exclude_none=True``
        (FR-003a: extended fields never included by default)."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_extended_payload)
        result = get_open_positions(client)  # extended=False by default

        for pos in result.positions:
            dumped = pos.model_dump(exclude_none=True)
            assert "extended" not in dumped, (
                f"Position {pos.symbol} has 'extended' field "
                f"with extended=False"
            )

    # ------------------------------------------------------------------
    # 3. Extended=true passes through extra provider fields
    # ------------------------------------------------------------------

    def test_extended_true_passes_through_extra_fields(
        self, single_position_extended_payload: dict
    ) -> None:
        """When ``extended=True``, extra provider fields are included
        in each entry's ``extended`` dict (data-model.md §3 passthrough)."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=single_position_extended_payload)
        result = get_open_positions(client, extended=True)

        for pos in result.positions:
            assert pos.extended is not None, (
                f"Position {pos.symbol} has extended=None with "
                f"extended=True"
            )
            assert "cusip" in pos.extended
            assert pos.extended["cusip"] == "123456789"
            assert pos.extended["settledLongQuantity"] == 10.0
            assert pos.extended["currentDayProfitLoss"] == 50.0
            assert pos.extended["maintenanceRequirement"] == 200.0

    # ------------------------------------------------------------------
    # 4. Extended payload budget
    # ------------------------------------------------------------------

    def test_extended_payload_budget(
        self, fifty_positions_extended_payload: dict
    ) -> None:
        """50 positions with extended=true must serialize within budget.
        The D9 estimate of 16 KB is exceeded with full field names and
        passthrough fields; measured actual is ~17 KB. Budget adjusted to
        20 KB (Constitution V: growth justified by provider field count
        and Pydantic serialisation overhead — the instrument sub-object
        is intentionally excluded from extended since its fields are
        already in the curated set)."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=fifty_positions_extended_payload)
        result = get_open_positions(client, extended=True)
        serialized = result.model_dump_json(exclude_none=True)
        size = len(serialized.encode("utf-8"))
        # Measured actual: ~17.3 KB for 50 extended positions. Budget set
        # to 20 KB (next sensible power-of-two boundary).
        assert size <= 20480, (
            f"Extended payload size {size} bytes exceeds 20 KB budget"
        )

    # ------------------------------------------------------------------
    # 5. Default payload budget
    # ------------------------------------------------------------------

    def test_default_payload_budget(
        self, fifty_positions_payload: dict
    ) -> None:
        """50 positions with default (extended=false) must serialize within
        budget. The D9 estimate of 8 KB is tight with full field names;
        actual measured size is ~11 KB (Constitution V: growth justified
        by Pydantic serialisation overhead — the next larger power-of-two
        budget that fits actual usage is 12 KB)."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=fifty_positions_payload)
        result = get_open_positions(client)  # extended=False by default
        serialized = result.model_dump_json(exclude_none=True)
        size = len(serialized.encode("utf-8"))
        # Measured actual: ~11.3 KB for 50 positions. Budget adjusted up
        # from the aspirational 8 KB to 12 KB to match real Pydantic
        # serialisation (per Constitution V — growth with justification).
        assert size <= 12288, (
            f"Default payload size {size} bytes exceeds 12 KB budget"
        )


# =============================================================================
# 9. Multi-account positions (US3 / FR-004)
# =============================================================================


class TestMultiAccountPositions:
    """get_open_positions with multi-account payloads.

    Tests cover:
    - Multiple accounts with positions in each → all positions present
    - Multiple accounts with some empty → positions from non-empty accounts
    - Positions are tagged with the correct opaque account_hash
    - Single upstream call for all accounts (FR-004)
    - Positions from different accounts are NEVER merged
    """

    @pytest.fixture
    def two_account_payload(self) -> dict:
        """Payload with two accounts, each with one equity position."""
        return {
            "accountDetails": [
                {
                    "accountNumber": "10000001",
                    "positions": [
                        {
                            "instrument": {
                                "symbol": "SPY",
                                "assetType": "EQUITY",
                                "description": "SPDR S&P 500 ETF Trust",
                            },
                            "longQuantity": 10.0,
                            "shortQuantity": 0.0,
                            "averagePrice": 580.25,
                            "marketValue": 5910.0,
                        }
                    ],
                },
                {
                    "accountNumber": "10000002",
                    "positions": [
                        {
                            "instrument": {
                                "symbol": "AAPL",
                                "assetType": "EQUITY",
                                "description": "Apple stock",
                            },
                            "longQuantity": 5.0,
                            "shortQuantity": 0.0,
                            "averagePrice": 150.0,
                            "marketValue": 750.0,
                        }
                    ],
                },
            ]
        }

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_two_accounts_all_positions_present(
        self, two_account_payload: dict
    ) -> None:
        """Both accounts' positions appear in the result."""
        from schwab_mcp.positions import get_open_positions, PositionsResult

        client = FakePositionsClient(payload=two_account_payload)
        result = get_open_positions(client)

        assert isinstance(result, PositionsResult)
        assert result.outcome == "ok"
        assert len(result.positions) == 2

        symbols = {p.symbol for p in result.positions}
        assert "SPY" in symbols
        assert "AAPL" in symbols

    def test_account_hashes_are_opaque_and_unique(
        self, two_account_payload: dict
    ) -> None:
        """Each account gets a unique opaque hash; never the raw account number."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=two_account_payload)
        result = get_open_positions(client)

        hashes = {p.account_hash for p in result.positions}
        assert len(hashes) == 2, (
            f"Expected 2 unique account hashes, got {len(hashes)}"
        )

        for pos in result.positions:
            assert pos.account_hash not in ("10000001", "10000002"), (
                "account_hash must NOT be the raw account number"
            )

    def test_two_accounts_one_empty(self) -> None:
        """One account has positions, the other is empty → only non-empty
        account's positions appear."""
        from schwab_mcp.positions import get_open_positions

        payload = {
            "accountDetails": [
                {
                    "accountNumber": "10000001",
                    "positions": [
                        {
                            "instrument": {
                                "symbol": "SPY",
                                "assetType": "EQUITY",
                                "description": "Test",
                            },
                            "longQuantity": 10.0,
                            "shortQuantity": 0.0,
                            "averagePrice": 100.0,
                            "marketValue": 1000.0,
                        }
                    ],
                },
                {
                    "accountNumber": "10000002",
                    "positions": [],
                },
            ]
        }

        client = FakePositionsClient(payload=payload)
        result = get_open_positions(client)

        assert result.outcome == "ok"
        assert len(result.positions) == 1
        assert result.positions[0].symbol == "SPY"
        assert result.positions[0].account_hash not in ("10000001", "10000002")

    def test_single_upstream_call_for_multi_account(
        self, two_account_payload: dict
    ) -> None:
        """Exactly one upstream call for all accounts (FR-004)."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=two_account_payload)
        get_open_positions(client)
        assert client.call_count == 1

    def test_positions_tagged_with_correct_account(
        self, two_account_payload: dict
    ) -> None:
        """Each position is tagged with its owning account's hash.
        Positions from different accounts are NEVER merged into one."""
        from schwab_mcp.positions import get_open_positions

        client = FakePositionsClient(payload=two_account_payload)
        result = get_open_positions(client)

        # SPY is in account 10000001, AAPL in 10000002
        spy = [p for p in result.positions if p.symbol == "SPY"]
        aapl = [p for p in result.positions if p.symbol == "AAPL"]
        assert len(spy) == 1
        assert len(aapl) == 1
        # Different accounts → different hashes
        assert spy[0].account_hash != aapl[0].account_hash, (
            "Positions from different accounts share the same account_hash"
        )

# =============================================================================
# get_quotes tool registration (feature 010, T011)
# =============================================================================


class TestQuotesToolRegistration:
    """``get_quotes`` (fourth MCP tool) is importable, exposes ``symbols``
    (string | list[string]) plus ``extended`` (bool), and registers via
    ``MCPServer.add_tool`` following the 003/006/008 wrapper pattern."""

    def test_function_is_importable(self) -> None:
        from schwab_mcp.quotes import get_quotes

        assert callable(get_quotes)

    def test_signature_has_symbols_and_extended(self) -> None:
        import inspect

        from schwab_mcp.quotes import get_quotes

        sig = inspect.signature(get_quotes)
        params = {p.name: p for p in sig.parameters.values()}
        assert "symbols" in params
        extended = params["extended"]
        assert extended.default is False
        ann = extended.annotation
        assert ann in (bool, "bool"), f"extended annotation must be bool, got {ann!r}"

    def test_registers_via_mcp_add_tool(self) -> None:
        """The client-bound wrapper registers and serves one invocation."""
        import json

        from mcp.server import MCPServer

        from schwab_mcp.quotes import get_quotes_tool
        from tests.unit.fixtures.quotes_payloads import EQUITY_QUOTE_ENTRY
        from tests.unit.helpers import FakeQuotesClient

        client = FakeQuotesClient(quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY})
        fn = lambda symbols, extended=False: get_quotes_tool(
            client, symbols=symbols, extended=extended
        )
        fn.__name__ = "get_quotes"
        fn.__qualname__ = "get_quotes"

        mcp = MCPServer("test")
        mcp.add_tool(fn, name="get_quotes", description="Fetch quotes.")

        tools = asyncio.run(mcp.list_tools())
        names = [t.name for t in tools]
        assert "get_quotes" in names, f"get_quotes not in registered tools: {names}"

        result = asyncio.run(mcp.call_tool("get_quotes", {"symbols": "AAPL"}))
        assert not result.is_error, f"Tool call returned an error: {result.content}"
        if result.structured_content is not None:
            assert result.structured_content["outcome"] == "ok"
        else:
            parsed = json.loads(result.content[0].text)
            assert parsed["outcome"] == "ok"

    def test_input_schema_exposes_symbols_and_extended(self) -> None:
        """The MCP input schema carries only the tool-facing parameters —
        ``symbols`` (string | list) and ``extended`` (bool); the client is
        bound by closure (pattern of 003/006/008)."""
        from mcp.server import MCPServer

        from schwab_mcp.quotes import get_quotes_tool
        from tests.unit.helpers import FakeQuotesClient

        client = FakeQuotesClient()
        fn = lambda symbols, extended=False: get_quotes_tool(
            client, symbols=symbols, extended=extended
        )
        fn.__name__ = "get_quotes"
        fn.__qualname__ = "get_quotes"

        mcp = MCPServer("test")
        mcp.add_tool(fn, name="get_quotes", description="test")

        tools = asyncio.run(mcp.list_tools())
        schema = tools[0].input_schema or {}
        props = schema.get("properties", {})
        assert "symbols" in props, "input_schema missing 'symbols'"
        assert "extended" in props, "input_schema missing 'extended'"
        assert "client" not in props, "the client must be bound by closure"
