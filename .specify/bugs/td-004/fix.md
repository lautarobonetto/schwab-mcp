# Bug Fix: TD-004 — Error envelopes and `ToolError` boundary divergent

- **Slug**: td-004
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Moved the four result-envelope builders into `tool_errors.py` with an
optional `symbol: str | None = None` (omitted from the envelope when
absent), deleted both modules' private copies, and routed the
`get_quotes_tool` / `get_price_history_tool` wrappers through the shared
`raise_classified_tool_error` with the auth taxonomy in their except
clause — closing the unclassified-escape gap. Emitted envelopes are
byte-identical to the pre-dedup shapes; expected-failure behavior on the
normal path is unchanged.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/tool_errors.py` | modified | Added shared builders `validation_error`, `provider_unreachable`, `reauth_needed`, `history_unavailable` (optional `symbol`, key order pinned); module docstring extended to cover both halves of the taxonomy |
| `src/schwab_mcp/quotes.py` | modified | Deleted 3 local envelope helpers; imports shared builders; wrapper now `except (AuthError, ValueError, TypeError) → raise_classified_tool_error` |
| `src/schwab_mcp/price_history.py` | modified | Deleted 4 local envelope helpers; imports shared builders; call sites pass `symbol=normalized`; wrapper same classified boundary |
| `tests/unit/test_tool_error_classification.py` | added tests | `TestQuotesToolClassifiedErrors` + `TestPriceHistoryToolClassifiedErrors` — taxonomy errors at the two new boundaries must become prefixed `ToolError`s |
| `tests/unit/test_quotes_mapping.py` | added tests | `TestSharedEnvelopeBuilders` — quotes-shape parity (no `symbol` key, pinned key order) |
| `tests/unit/test_price_history_mapping.py` | added tests | `TestSharedEnvelopeBuilders` — symbol-carrying parity incl. `history_unavailable`, `symbol` between `retryable` and extras |
| `tests/unit/test_price_history_validation.py` | modified | Stale comment referencing deleted `quotes._validation_error` now points at `tool_errors.validation_error` |
| `docs/CHANGELOG.md` | modified | TD-004 entry under `[0.9.8] → Changed` |
| `docs/tech-debt.md` | modified | TD-004 marked Fixed (table + Resolved paragraph); TD-016 row for the deleted `quotes.py:137` helper removed |

## Diff Highlights

Shared builders with the omit-when-absent `symbol`:

```python
# src/schwab_mcp/tool_errors.py
def validation_error(detail: str, symbol: str | None = None, **extra: Any) -> dict:
    envelope: dict[str, Any] = {
        "outcome": "validation_error",
        "detail": detail,
        "retryable": False,
    }
    if symbol is not None:
        envelope["symbol"] = symbol
    envelope.update(extra)
    return envelope
```

Classified boundary, identical shape in both market-data wrappers:

```python
# src/schwab_mcp/quotes.py (and price_history.py)
    from schwab_mcp.errors import AuthError
    from schwab_mcp.tool_errors import raise_classified_tool_error

    try:
        return get_quotes(client, symbols, extended=extended)
    except (AuthError, ValueError, TypeError) as exc:
        raise_classified_tool_error(exc)
```

## Tests Added or Updated

- `tests/unit/test_tool_error_classification.py::TestQuotesToolClassifiedErrors::test_taxonomy_errors_become_classified_tool_error[connectivity|reauth]` — a `ConnectivityError`/`ReauthorizationRequiredError` escaping the domain must surface as an exact `ToolError` with the `provider_unreachable:`/`reauth_needed:` prefix (failed Red before the fix: the exception escaped raw)
- `tests/unit/test_tool_error_classification.py::TestPriceHistoryToolClassifiedErrors::...` — same contract for `get_price_history_tool`
- `tests/unit/test_quotes_mapping.py::TestSharedEnvelopeBuilders` (5 tests) — shared builders emit byte-identical quotes envelopes, `symbol` key absent, pinned key order
- `tests/unit/test_price_history_mapping.py::TestSharedEnvelopeBuilders` (4 tests) — symbol-carrying envelopes incl. `history_unavailable`, `symbol` between `retryable` and extras

TDD: all 13 new tests failed first (Red) — 4 with the raw escaping `ConnectivityError`, 9 on the missing shared builders — then passed after the implementation (Green).

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_tool_error_classification.py tests/unit/test_quotes_mapping.py tests/unit/test_price_history_mapping.py -q` → 62 passed (Green)
  - `uv run pytest -q` (full suite) → **1787 passed, 0 skipped** (run again after doc edits: same result)
- Manual checks:
  - No remaining references to `_validation_error` / `_provider_unreachable` / `_reauth_needed` / `_history_unavailable` or direct `ToolError` imports in the two market-data modules (grep clean)
  - All three touched test/source files parse (`ast.parse` check during the edit)
  - Envelope call-site shapes preserved: quotes passes no `symbol`; `price_history._fail` passes `symbol` positionally; the three taxonomy call sites pass `symbol=normalized`

## Deviations from Assessment

- **Scope expansion (logged, constitution-mandated)**: `docs/tech-debt.md` and
  `tests/unit/test_price_history_validation.py` were not in the assessment's
  file list. `docs/tech-debt.md` tracks TD-004 and a TD-016 row pointing at
  the deleted `quotes.py:137` helper — both updated per the affected-docs
  rule. The validation test module docstring referenced the now-deleted
  `quotes._validation_error`; the comment was updated (no assertion change).
- `docs/tools.md` needed **no** change: the normal-path envelope contract is
  untouched, and the classified-prefix table (`docs/tools.md:46-47`) already
  describes the prefixes generically.
- The assessment suggested the TDD test as "a `ConnectivityError` raised
  *inside* `get_quotes`"; as the assessment itself noted, the error must be
  raised at the domain-function boundary (monkeypatch, matching the file's
  existing technique) — inside the domain it is correctly converted to an
  envelope. Tests were written that way; no deviation in substance.

## Follow-ups

- The shared `provider_unreachable(detail="provider_unreachable", ...)` keeps
  the defaulted `detail` that the removed TD-016 row flagged at
  `quotes.py:137` — the nit now lives in `tool_errors.py`; consider requiring
  `detail` explicitly if TD-016 is worked.
- TD-010 (`price_history.py` failure-event pattern repeated manually) touches
  the same call sites; worth doing with the now-shared builders in hand.
- Consider whether `quotes.py`'s remaining top-level
  `ReauthorizationRequiredError` import (used only in an `isinstance` check)
  could import from `tool_errors` instead once TD-005/TD-006 consolidate the
  boundary layer.