# Bug Fix: TD-010 — `price_history.py`: failure-event pattern repeated manually (DRY)

- **Slug**: td-010-price-history-fail-dry
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Applied the assessment's preferred remediation: a `fail(detail, **extra)` closure now binds the selection tuple once after symbol normalization and backs all seven validation-ladder failure returns; a `_fail_event(detail, ...)` helper is the single place where the `f"{reason} " + _selection_detail(...)` detail composition lives; the `ConnectivityError` handler collapsed to one emission path; the success event now logs via the same composition path with `normalized`. Behavior is strictly preserved — same event names, detail strings, classifications, and envelopes.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/price_history.py` | modified | Added `_fail_event` helper (~line 179) and refactored `_fail` to compose through it. |
| `src/schwab_mcp/price_history.py` | modified | Added `fail(...)` / `fail_event(...)` closures in `get_price_history` right after normalization (lines 472–484). |
| `src/schwab_mcp/price_history.py` | modified | Seven `_fail` call sites converted to one-line `fail(...)` calls (lines 486–512). |
| `src/schwab_mcp/price_history.py` | modified | `ConnectivityError` handler collapsed to one parameterized emission path (lines 530–541). |
| `src/schwab_mcp/price_history.py` | modified | `invalid_request`, `history_unavailable`, and success event details now built via `_fail_event`/`fail_event` (lines 460, 554, 595). |
| `tests/unit/*price_history*` | unchanged | Characterization coverage verified complete before refactoring (see below); tests stayed green unchanged — that is the regression gate. |

## Diff Highlights

Closures bound once after normalization:

```python
normalized = (symbol or "").strip().upper()

def fail(detail: str, **extra: Any) -> dict:
    """Emit the failure event + envelope with the bound selection."""
    return _fail(detail, normalized, frequency, period, extended_hours, extended, **extra)

def fail_event(detail: str) -> str:
    """Composed event detail for the bound selection (contract §6)."""
    return _fail_event(detail, normalized, frequency, period, extended_hours, extended)
```

Validation ladder — seven multi-line calls became one-liners:

```python
if not normalized:
    return fail("malformed_symbol")
...
if frequency not in PRESET_TABLE:
    return fail("unsupported_frequency", valid_frequencies=list(PRESET_TABLE))
```

`ConnectivityError` — one emission path, envelope as data:

```python
except ConnectivityError as exc:
    reauth = isinstance(exc.__cause__, (ReauthorizationRequiredError, PermissionError))
    state, reason, envelope = (
        ("reauth", "reauth_needed", reauth_needed)
        if reauth
        else ("provider_unreachable", "provider_unreachable", provider_unreachable)
    )
    auth_event(FAILURE_EVENT, state, detail=fail_event(reason))
    return envelope(symbol=normalized)
```

## Tests Added or Updated

- None added. Per the assessment's gate, characterization coverage was verified **before** refactoring: `tests/unit/test_price_history_events.py` pins the start/failure/success event names and outcomes for every failure reason (`missing`, `malformed`, `option-kind`, `bad-frequency`, `bad-period`, `extended-hours`, no-candles→`error`, 500/502/408/429 and transport→`provider_unreachable`, 401/403→`reauth`), the symbol+selection detail content, and the no-secrets contract; `tests/unit/test_price_history_validation.py` pins the envelopes. No gaps found, so no new tests were required. The suite passing **unchanged** is the proof of behavior preservation.

## Local Verification

- `uv run pytest tests/unit/test_price_history_events.py tests/unit/test_price_history_validation.py tests/unit/test_price_history_mapping.py tests/unit/test_price_history_in_progress.py tests/unit/test_price_history_aggregation.py -q` → 226 passed.
- `uv run pytest -q` (full suite, commit gate) → **1819 passed, 0 skipped** in 33.48s.
- Manual check: re-read the full `get_price_history` body post-refactor to confirm event names, classifications, detail strings, and envelope arguments are byte-identical to the pre-refactor emissions; also confirmed the two lines that exceeded the file's ~88-char style were wrapped (no linter configured in this project).

## Deviations from Assessment

- **START event still passes raw `symbol`** (assessment suggested passing `normalized` everywhere). The START event must precede the tool-boundary type check: a non-string `symbol` would crash normalization (`int.strip()`), dropping the start event from the `TypeError` path — a behavior change. Since `_selection_detail` normalizes internally, the emitted string is identical either way, so the raw argument is left in place. Zero output impact; cosmetic only.
- **Collapse form**: the assessment offered "a local helper or a two-tuple lookup"; implemented the two-tuple (state, reason, envelope) form rather than an extra local function — fewer moving parts (KISS), identical effect.

## Follow-ups

- The same detail-composition and fail-tuple patterns may exist in sibling tools (`transactions.py`, `quotes.py`); if a future TD confirms recurrence, consider a shared selection-binding helper across tools (explicitly out of scope here per the assessment).
- Commit per constitution: full suite green, docs affected by the audit-event surface unchanged (no doc updates needed — behavior preserved).