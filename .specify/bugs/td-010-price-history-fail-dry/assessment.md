# Bug Assessment: TD-010 — `price_history.py`: failure-event pattern repeated manually (DRY)

- **Slug**: td-010-price-history-fail-dry
- **Created**: 2026-11-04
- **Source**: pasted text (TD-010 technical-debt report)
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

Pasted TD-010 report against `src/schwab_mcp/price_history.py`:

> - `_fail` invoked six times repeating the same 5-argument tuple
>   `(normalized, frequency, period, extended_hours, extended)`
>   (`488-557`).
> - The event-detail composition `f"{detail} " + _selection_detail(...)`
>   repeated five times (`226, 473-476, 582-585, 591-594, 609-612`).
> - Inconsistency exposing the manual duplication: failure events log the
>   normalized symbol, the success event (`653-656`) logs the raw one —
>   the same instrument appears under two keys.
> - The `ConnectivityError` handler duplicates reauth/unreachable branches
>   (`575-596`).

**Corrections found during triage** (report appears written against an older revision; current line numbers differ):

1. `_fail` is invoked **seven** times, not six — lines 459, 470, 478, 488, 498, 510, 521. Each repeats the same positional tail `(normalized, frequency, period, extended_hours, extended)`. The duplication claim itself stands.
2. The claimed **symbol-key inconsistency is factually incorrect**. `_selection_detail` (line 172) normalizes internally — `name = symbol.strip().upper()` — so the success event (line 625, passing raw `symbol`) and the failure paths (passing `normalized`) emit the *identical* normalized `symbol=...` string. There is no "same instrument under two keys" in the audit log. The real (much smaller) issue is stylistic: raw `symbol` is passed at START/success while `normalized` is passed to `_fail`, and `_fail`'s argument is then re-normalized inside `_selection_detail`.
3. The stale line references map to current locations: detail composition duplicated in `_fail` itself (line 197) plus inline at 444–447 (`invalid_request`), 553–555 (`reauth_needed`), 562–564 (`provider_unreachable`), 580–582 (`history_unavailable`), and 624–627 (success event).

## Symptom

This is a code-health (DRY/KISS) issue, not a runtime defect: seven `_fail` calls and five inline event-detail compositions repeat the same parameter plumbing, and the `ConnectivityError` handler repeats two near-identical branches that differ only in reason string and envelope function (`reauth_needed` vs `provider_unreachable`). Expected (per project Principle II/III): one parameterized path; a change to the event-detail shape or the fail tuple should require editing one place.

## Reproduction

Not a runtime bug — reproducible by code inspection:

1. Open `src/schwab_mcp/price_history.py`.
2. Count `_fail(` call sites (7) and `+ _selection_detail(` composition sites (7 including `_fail` and the success event).
3. Compare lines 546–567 (`ConnectivityError` handler): the two branches are structurally identical except for `"reauth"` / `"reauth_needed "` vs `"provider_unreachable"` / `provider_unreachable(...)`.

## Suspected Code Paths

- `src/schwab_mcp/price_history.py:179` — `_fail(detail, symbol, frequency, period, extended_hours, extended, **extra)`: already the shared envelope builder, but every caller still passes the full 5-arg tail manually.
- `src/schwab_mcp/price_history.py:459, 470, 478, 488, 498, 510, 521` — seven `_fail` calls repeating `(normalized, frequency, period, extended_hours, extended)`.
- `src/schwab_mcp/price_history.py:197, 444-447, 553-555, 562-564, 580-582, 624-627` — `f"{detail} " + _selection_detail(...)` composed repeatedly.
- `src/schwab_mcp/price_history.py:546-567` — `ConnectivityError` handler with duplicated reauth/unreachable branches.
- `src/schwab_mcp/price_history.py:160-176` — `_selection_detail` already normalizes the symbol internally; relevant to the (incorrect) inconsistency claim.

## Root Cause Hypothesis

Confidence: **high**. The failure path was written call-site by call-site as the validation ladder grew (malformed symbol → unsupported kind → frequency → period → extended-hours), each step copying the same tuple and detail composition instead of binding the selection once. The `ConnectivityError` branches follow the same pattern. This mirrors previously resolved TD items (td-006, td-007, td-008, transaction-result-dry), so it is an established debt class in this codebase, not a one-off.

## Proposed Remediation

**Preferred**: Inside `get_price_history`, immediately after normalization (line 457), bind the selection once with a closure:

```python
def fail(detail: str, **extra: Any) -> dict:
    return _fail(detail, normalized, frequency, period, extended_hours, extended, **extra)
```

Then convert the seven call sites to `return fail("malformed_symbol")`, `return fail("unsupported_frequency", valid_frequencies=list(PRESET_TABLE))`, etc. Introduce a small `_fail_event(detail) -> str` helper (or reuse `_fail`'s internal composition) so the inline sites (`invalid_request`, `reauth_needed`, `provider_unreachable`, `history_unavailable`, success) call it instead of re-composing `f"{detail} " + _selection_detail(...)`. Collapse the `ConnectivityError` handler into one parameterized branch, e.g. a local helper `_connectivity_failure(reason, event_state, envelope)` or a two-tuple lookup, keeping `reauth_needed(symbol=normalized)` / `provider_unreachable(symbol=normalized)` as the only differences. For consistency (cosmetic, zero output change), pass `normalized` at the START and success events too — `_selection_detail` already guarantees identical log output either way.

Keep the change strictly behavior-preserving: same event names, same detail strings, same envelopes. This is refactor-phase work; the existing suite is the gate.

**Alternatives**:
- Pass a frozen dataclass / NamedTuple `Selection` (symbol, frequency, period, extended_hours, extended) through the function instead of a closure. More explicit and testable, but heavier and inconsistent with the module's plain-function style; overkill for one function.
- Extend the deduplication to the sibling tools (`transactions.py`, etc.) with a shared helper. Tempting, but out of scope for TD-010 — flag as a possible follow-up TD only if the pattern recurs; KISS says don't abstract across modules on one data point.

**Files likely to change**:
- `src/schwab_mcp/price_history.py`
- (no test changes expected unless characterization coverage is missing)

**Tests to add or update**:
- Existing `tests/unit/test_price_history_events.py` (asserts FAILURE_EVENT detail strings) and `tests/unit/test_price_history_validation.py` (asserts envelopes) already lock the behavior — they must stay green unchanged; that is the regression gate.
- Gap check: verify the events suite covers all seven `_fail` reasons plus `invalid_request`, `reauth_needed`, `provider_unreachable`, and `history_unavailable` detail strings; add any missing characterization tests **before** refactoring (constitution TDD: characterization first, then refactor).

## Risks & Considerations

- Low risk overall: pure refactor inside one function, no API change, no data change.
- The main hazard is accidental drift in audit-event detail strings, which downstream consumers may match on — the events tests are the guard; keep them untouched.
- Closure captures `normalized`/`frequency`/etc. by reference; all are never reassigned after line 457, so no stale-capture hazard — but keep the closure defined after normalization for clarity.
- Success/START events switching from raw `symbol` to `normalized`: output is provably identical (`_selection_detail` normalizes), but review the diff carefully to confirm no path passes a non-string to the closure path.

## Open Questions

- None blocking. (The report's symbol-inconsistency claim was checked and found incorrect; no user clarification needed.)