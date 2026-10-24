"""Failing unit tests for ``OptionChainQuery`` input validation (FR-008).

These are TDD red-phase tests: ``schwab_mcp.options_chain`` does not exist
yet, so every test fails with ``ModuleNotFoundError``. Once implemented,
all tests should pass.

Covers (from tasks.md T002)
---------------------------
- ``symbol`` non-empty, without internal whitespace
- ``max_strikes >= 1`` (default 50)
- ``option_type`` in {``both``, ``calls``, ``puts``} (default ``both``)
- ``delta_target`` with ``0 < |delta_target| < 1`` or ``null`` (default null)
- ``dte_max >= 1`` or ``null`` (default null -> effective cap 60)
- Actionable error message for every case

Design constraints (data-model.md §1, verbatim)
-----------------------------------------------
``symbol``:
    "no vacío, sin espacios internos; se pasa tal cual al proveedor
    (el matching/normalización es del proveedor)"
``max_strikes``:
    "≥ 1"
``option_type``:
    "valor del enum" (enum ``both`` | ``calls`` | ``puts``)
``delta_target``:
    "si presente: 0 < |delta_target| < 1"
``dte_max``:
    "si presente: ≥ 1; si ausente, tope vigente = 60"

Semántica de defaults (data-model.md §1): ``dte_max=null`` NO significa
"sin tope" — significa "no elijo DTE" y aplica el tope por defecto de
60 días (FR-005).

References
----------
- specs/008-extract-option-chain/spec.md (FR-008)
- specs/008-extract-option-chain/data-model.md (§1 OptionChainQuery)
- tmp/008-api-brief.md (binding API contract: ``OptionChainQuery``,
  ``validate()``, ``dte_max_effective``)
"""

from __future__ import annotations

import pytest


# =============================================================================
# Defaults
# =============================================================================


class TestDefaults:
    """Defaults per data-model.md §1: ``max_strikes`` = 50, ``option_type`` =
    ``both``, ``delta_target`` = null, ``dte_max`` = null (tope vigente = 60).

    Verbatim constraints:
    - ``max_strikes``: "≥ 1" (default ``50``)
    - ``option_type``: "valor del enum" (default ``both``)
    - ``delta_target``: "si presente: 0 < |delta_target| < 1" (default ``null``)
    - ``dte_max``: "si presente: ≥ 1; si ausente, tope vigente = 60"
    """

    def test_defaults(self) -> None:
        """``OptionChainQuery(symbol="AAPL")`` applies the documented defaults.

        Constraint (data-model.md §1): ``max_strikes`` default ``50``;
        ``option_type`` default ``both``; ``delta_target`` default ``null``;
        ``dte_max`` default ``null`` — "si ausente, tope vigente = 60".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        query = OptionChainQuery(symbol="AAPL")
        assert query.max_strikes == 50
        assert query.option_type == "both"
        assert query.delta_target is None
        assert query.dte_max is None
        assert query.dte_max_effective == 60

    def test_validate_passes_with_defaults(self) -> None:
        """``validate()`` returns ``None`` for a default query with a valid
        symbol.

        Constraint (data-model.md §1): ``symbol`` "no vacío, sin espacios
        internos"; all other fields at their defaults satisfy their
        constraints ("≥ 1", "valor del enum", "si presente: 0 <
        |delta_target| < 1", "si presente: ≥ 1; si ausente, tope vigente = 60").
        """
        from schwab_mcp.options_chain import OptionChainQuery

        query = OptionChainQuery(symbol="AAPL")
        assert query.validate() is None

    def test_dte_max_effective_uses_requested_value(self) -> None:
        """``dte_max=120`` -> ``dte_max_effective == 120``.

        Constraint (data-model.md §1): ``dte_max`` "si presente: ≥ 1; si
        ausente, tope vigente = 60" — when present, the requested value is
        the effective cap.
        """
        from schwab_mcp.options_chain import OptionChainQuery

        query = OptionChainQuery(symbol="AAPL", dte_max=120)
        assert query.dte_max_effective == 120


# =============================================================================
# symbol
# =============================================================================


class TestSymbolValidation:
    """``symbol`` validation per data-model.md §1, verbatim:

    "no vacío, sin espacios internos; se pasa tal cual al proveedor (el
    matching/normalización es del proveedor)"
    """

    def test_symbol_empty_string(self) -> None:
        """Empty ``symbol`` is rejected.

        Constraint (data-model.md §1): ``symbol`` "no vacío, sin espacios
        internos; se pasa tal cual al proveedor (el matching/normalización es
        del proveedor)". Error must be a ``ValueError`` mentioning ``symbol``
        and "must not be empty".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="")
            query.validate()
        msg = str(excinfo.value)
        assert "symbol" in msg
        assert "must not be empty" in msg

    def test_symbol_whitespace_only(self) -> None:
        """Whitespace-only ``symbol`` is rejected as empty.

        Constraint (data-model.md §1): ``symbol`` "no vacío, sin espacios
        internos; se pasa tal cual al proveedor (el matching/normalización es
        del proveedor)". Error must be a ``ValueError`` mentioning ``symbol``
        and "must not be empty".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="   ")
            query.validate()
        msg = str(excinfo.value)
        assert "symbol" in msg
        assert "must not be empty" in msg

    def test_symbol_internal_whitespace(self) -> None:
        """``symbol`` with internal whitespace (e.g. ``"AA PL"``) is rejected.

        Constraint (data-model.md §1): ``symbol`` "no vacío, sin espacios
        internos; se pasa tal cual al proveedor (el matching/normalización es
        del proveedor)". Error must be a ``ValueError`` mentioning ``symbol``
        and "internal whitespace".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="AA PL")
            query.validate()
        msg = str(excinfo.value)
        assert "symbol" in msg
        assert "internal whitespace" in msg

    def test_symbol_not_a_string(self) -> None:
        """Non-str ``symbol`` is rejected with ``TypeError``.

        Constraint (data-model.md §1): ``symbol`` is a "string" — "no vacío,
        sin espacios internos; se pasa tal cual al proveedor (el
        matching/normalización es del proveedor)". Error must be a
        ``TypeError`` mentioning ``symbol``.
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(TypeError) as excinfo:
            query = OptionChainQuery(symbol=12345)  # type: ignore[arg-type]
            query.validate()
        assert "symbol" in str(excinfo.value)


# =============================================================================
# max_strikes
# =============================================================================


class TestMaxStrikesValidation:
    """``max_strikes`` validation per data-model.md §1, verbatim: "≥ 1"."""

    def test_max_strikes_zero(self) -> None:
        """``max_strikes=0`` is rejected.

        Constraint (data-model.md §1): ``max_strikes`` "≥ 1". Error must be a
        ``ValueError`` mentioning ``max_strikes`` and ">= 1".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="AAPL", max_strikes=0)
            query.validate()
        msg = str(excinfo.value)
        assert "max_strikes" in msg
        assert ">= 1" in msg

    def test_max_strikes_negative(self) -> None:
        """``max_strikes=-1`` is rejected.

        Constraint (data-model.md §1): ``max_strikes`` "≥ 1". Error must be a
        ``ValueError`` mentioning ``max_strikes`` and ">= 1".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="AAPL", max_strikes=-1)
            query.validate()
        msg = str(excinfo.value)
        assert "max_strikes" in msg
        assert ">= 1" in msg

    def test_max_strikes_not_an_int(self) -> None:
        """Non-int ``max_strikes`` is rejected with ``TypeError``.

        Constraint (data-model.md §1): ``max_strikes`` is an "int" — "≥ 1".
        Error must be a ``TypeError`` mentioning ``max_strikes``.
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(TypeError) as excinfo:
            query = OptionChainQuery(symbol="AAPL", max_strikes="10")  # type: ignore[arg-type]
            query.validate()
        assert "max_strikes" in str(excinfo.value)


# =============================================================================
# option_type
# =============================================================================


class TestOptionTypeValidation:
    """``option_type`` validation per data-model.md §1, verbatim: "valor del
    enum" (enum ``both`` | ``calls`` | ``puts``).
    """

    def test_option_type_strangles(self) -> None:
        """``option_type="strangles"`` is outside the enum and is rejected.

        Constraint (data-model.md §1): ``option_type`` "valor del enum" (enum
        ``both`` | ``calls`` | ``puts``). Error must be a ``ValueError``
        mentioning ``option_type`` and "both, calls, puts".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="AAPL", option_type="strangles")
            query.validate()
        msg = str(excinfo.value)
        assert "option_type" in msg
        assert "both, calls, puts" in msg

    def test_option_type_wrong_case(self) -> None:
        """``option_type="ALL"`` is outside the enum (case-sensitive) and is
        rejected.

        Constraint (data-model.md §1): ``option_type`` "valor del enum" (enum
        ``both`` | ``calls`` | ``puts``). Error must be a ``ValueError``
        mentioning ``option_type`` and "both, calls, puts".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="AAPL", option_type="ALL")
            query.validate()
        msg = str(excinfo.value)
        assert "option_type" in msg
        assert "both, calls, puts" in msg

    def test_option_type_empty_string(self) -> None:
        """``option_type=""`` is outside the enum and is rejected.

        Constraint (data-model.md §1): ``option_type`` "valor del enum" (enum
        ``both`` | ``calls`` | ``puts``). Error must be a ``ValueError``
        mentioning ``option_type`` and "both, calls, puts".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="AAPL", option_type="")
            query.validate()
        msg = str(excinfo.value)
        assert "option_type" in msg
        assert "both, calls, puts" in msg


# =============================================================================
# delta_target
# =============================================================================


class TestDeltaTargetValidation:
    """``delta_target`` validation per data-model.md §1, verbatim: "si
    presente: 0 < |delta_target| < 1".
    """

    def test_delta_target_zero(self) -> None:
        """``delta_target=0`` is rejected (strict inequality).

        Constraint (data-model.md §1): ``delta_target`` "si presente:
        0 < |delta_target| < 1". Error must be a ``ValueError`` mentioning
        ``delta_target`` and "0 < |delta_target| < 1".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="AAPL", delta_target=0)
            query.validate()
        msg = str(excinfo.value)
        assert "delta_target" in msg
        assert "0 < |delta_target| < 1" in msg

    def test_delta_target_negative_zero(self) -> None:
        """``delta_target=-0.0`` is rejected (``abs(-0.0) == 0.0``, not > 0).

        Constraint (data-model.md §1): ``delta_target`` "si presente:
        0 < |delta_target| < 1". Error must be a ``ValueError`` mentioning
        ``delta_target`` and "0 < |delta_target| < 1".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="AAPL", delta_target=-0.0)
            query.validate()
        msg = str(excinfo.value)
        assert "delta_target" in msg
        assert "0 < |delta_target| < 1" in msg

    def test_delta_target_above_one(self) -> None:
        """``delta_target=1.5`` is rejected (``abs() >= 1``).

        Constraint (data-model.md §1): ``delta_target`` "si presente:
        0 < |delta_target| < 1". Error must be a ``ValueError`` mentioning
        ``delta_target`` and "0 < |delta_target| < 1".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="AAPL", delta_target=1.5)
            query.validate()
        msg = str(excinfo.value)
        assert "delta_target" in msg
        assert "0 < |delta_target| < 1" in msg

    def test_delta_target_equal_to_one(self) -> None:
        """``delta_target=1.0`` is rejected (strict inequality, ``< 1``).

        Constraint (data-model.md §1): ``delta_target`` "si presente:
        0 < |delta_target| < 1". Error must be a ``ValueError`` mentioning
        ``delta_target`` and "0 < |delta_target| < 1".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="AAPL", delta_target=1.0)
            query.validate()
        msg = str(excinfo.value)
        assert "delta_target" in msg
        assert "0 < |delta_target| < 1" in msg

    def test_delta_target_equal_to_negative_one(self) -> None:
        """``delta_target=-1.0`` is rejected (``abs(-1.0) == 1.0``, not < 1).

        Constraint (data-model.md §1): ``delta_target`` "si presente:
        0 < |delta_target| < 1". Error must be a ``ValueError`` mentioning
        ``delta_target`` and "0 < |delta_target| < 1".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="AAPL", delta_target=-1.0)
            query.validate()
        msg = str(excinfo.value)
        assert "delta_target" in msg
        assert "0 < |delta_target| < 1" in msg

    @pytest.mark.parametrize("delta_target", [0.20, -0.20, 0.999, -0.05])
    def test_delta_target_valid_values(self, delta_target: float) -> None:
        """Valid ``delta_target`` values pass validation.

        Constraint (data-model.md §1): ``delta_target`` "si presente:
        0 < |delta_target| < 1" — both signs are allowed, the bound is on the
        absolute value.
        """
        from schwab_mcp.options_chain import OptionChainQuery

        query = OptionChainQuery(symbol="AAPL", delta_target=delta_target)
        assert query.validate() is None


# =============================================================================
# dte_max
# =============================================================================


class TestDteMaxValidation:
    """``dte_max`` validation per data-model.md §1, verbatim: "si presente:
    ≥ 1; si ausente, tope vigente = 60".
    """

    def test_dte_max_zero(self) -> None:
        """``dte_max=0`` is rejected.

        Constraint (data-model.md §1): ``dte_max`` "si presente: ≥ 1; si
        ausente, tope vigente = 60". Error must be a ``ValueError`` mentioning
        ``dte_max`` and ">= 1".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="AAPL", dte_max=0)
            query.validate()
        msg = str(excinfo.value)
        assert "dte_max" in msg
        assert ">= 1" in msg

    def test_dte_max_negative(self) -> None:
        """``dte_max=-3`` is rejected.

        Constraint (data-model.md §1): ``dte_max`` "si presente: ≥ 1; si
        ausente, tope vigente = 60". Error must be a ``ValueError`` mentioning
        ``dte_max`` and ">= 1".
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(ValueError) as excinfo:
            query = OptionChainQuery(symbol="AAPL", dte_max=-3)
            query.validate()
        msg = str(excinfo.value)
        assert "dte_max" in msg
        assert ">= 1" in msg

    def test_dte_max_not_an_int(self) -> None:
        """Non-int ``dte_max`` is rejected with ``TypeError``.

        Constraint (data-model.md §1): ``dte_max`` is an "int | null" — "si
        presente: ≥ 1; si ausente, tope vigente = 60". Error must be a
        ``TypeError`` mentioning ``dte_max``.
        """
        from schwab_mcp.options_chain import OptionChainQuery

        with pytest.raises(TypeError) as excinfo:
            query = OptionChainQuery(symbol="AAPL", dte_max="30")  # type: ignore[arg-type]
            query.validate()
        assert "dte_max" in str(excinfo.value)

    def test_dte_max_valid_value(self) -> None:
        """``dte_max=7`` passes validation and is the effective cap.

        Constraint (data-model.md §1): ``dte_max`` "si presente: ≥ 1; si
        ausente, tope vigente = 60" — when present, the requested value is
        the effective cap (``dte_max_effective == 7``).
        """
        from schwab_mcp.options_chain import OptionChainQuery

        query = OptionChainQuery(symbol="AAPL", dte_max=7)
        assert query.validate() is None
        assert query.dte_max_effective == 7
