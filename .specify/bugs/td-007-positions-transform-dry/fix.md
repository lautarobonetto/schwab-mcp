# Bug Fix: TD-007 — `positions.py`: transform layer remaps itself (DRY/KISS)

- **Slug**: td-007-positions-transform-dry
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Consolidated the positions pipeline per the assessment's preferred
remediation: `unrealized_pl` is now computed exactly once (at
`PositionEntry` construction), the dead consolidation-map key and the
transform-layer `unrealizedPL` bake are gone, `_collect_extended`
replaces the inline loop, the defensive timestamp override is removed,
every `PositionsResult` is built with `ResultOutcome`/`DetailType` (and
`AccountFailureDetail`) enum members, the partial-failure path constructs
its result in a single `map_provider_positions` call instead of mutating
a validated result, and the dead `retrieved_at` parameter of
`_detect_account_failures` is gone. No behavior change; full suite green.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/positions.py` | modified | `_transform_provider_payload`: dropped the `unrealizedPL` computation, replaced the inline extended loop with `_collect_extended`, docstring states P/L is not part of the internal payload |
| `src/schwab_mcp/positions.py` | modified | consolidation map: removed the never-read `unrealized_pl` key (comment left at the site) |
| `src/schwab_mcp/positions.py` | modified | `map_provider_positions`: new `outcome` / `detail` / `accounts_failed` / `retryable` params; both result constructions use them with `DetailType` fallbacks (`NO_POSITIONS` / `DATA_RECEIVED`) |
| `src/schwab_mcp/positions.py` | modified | `get_open_positions`: all four result constructions use enum members; partial path builds via `map_provider_positions(..., outcome=PARTIAL_FAILURE, ...)` in one call; timestamp override block deleted; audit comparisons use `OutcomeType` members |
| `src/schwab_mcp/positions.py` | modified | `_detect_account_failures(provider_payload)`: dead `retrieved_at` param removed; detail values now `AccountFailureDetail.TRANSIENT` / `PROVIDER_ERROR`; unmatched-account list in the orchestrator also uses the enum |
| `tests/unit/test_positions.py` | modified | transform test rewritten: `test_transform_payload_option_upl_multiplied` → `test_transform_payload_carries_no_unrealized_pl` (asserts key absent from internal payload and multiplier still lands on `PositionEntry.unrealized_pl`) |
| `tests/unit/test_positions.py` | added tests | `TestMapProviderPositionsOutcomeParams`: ok/no_positions defaults use enum members; partial-failure single-call construction; `ok` + `accounts_failed` rejected at construction (validator window) |
| `tests/unit/test_server_tool.py` | added tests | `TestPartialFailure` + `partial_failure_payload` fixture: orchestration-level partial failure — outcome/detail/accounts_failed (only the error account, opaque hash)/positions from the successful account/retryable/enum membership |

## Diff Highlights

Single `unrealized_pl` computation (was three):

```python
# _transform_provider_payload — removed:
-   "unrealizedPL": _compute_unrealized_pl(...),

# consolidation map — removed:
-   "unrealized_pl": _compute_unrealized_pl(...),

# PositionEntry construction — the only call site left:
    "unrealized_pl": _compute_unrealized_pl(
        data["market_value"], data["average_price"], data["quantity"],
        data["instrument_type"],
    ),
```

Partial-failure path, one construction instead of mutate-after-validate:

```python
-   pos_result = map_provider_positions(internal_payload, extended=extended)
-   pos_result.outcome = "partial_failure"
-   pos_result.detail = "account_failed"
-   pos_result.accounts_failed = accounts_failed_list
-   pos_result.retryable = False
+   pos_result = map_provider_positions(
+       internal_payload,
+       extended=extended,
+       outcome=OutcomeType.PARTIAL_FAILURE,
+       detail=DetailType.ACCOUNT_FAILED,
+       accounts_failed=accounts_failed_list,
+       retryable=False,
+   )
```

Dead defensive work removed:

```python
-   # Override timestamps
-   pos_result.retrieved_at = retrieved_at
-   for entry in pos_result.positions:
-       entry.price_timestamp = retrieved_at
```

The Red run confirmed the assessment's diagnosis directly: with the old
mutate-after-map flow, `accounts_failed` entries stayed raw **dicts**
(pydantic v2 does not validate post-hoc assignment), so the new test
`test_accounts_failed_lists_only_the_error_account` failed with
`'dict' object has no attribute 'account_hash'` before the fix — exactly
the validator bypass the report described.

## Tests Added or Updated

- `tests/unit/test_positions.py::TestUnrealizedPlOptionMultiplier::test_transform_payload_carries_no_unrealized_pl` — internal payload carries no `unrealizedPL`; option multiplier still surfaces on `PositionEntry.unrealized_pl` (−6616.29 pinned).
- `tests/unit/test_positions.py::TestMapProviderPositionsOutcomeParams::test_ok_defaults_use_enum_members` — default construction uses `OutcomeType.OK` / `DetailType.DATA_RECEIVED`.
- `tests/unit/test_positions.py::TestMapProviderPositionsOutcomeParams::test_no_positions_default_uses_no_positions_detail` — empty mapping defaults to `DetailType.NO_POSITIONS`.
- `tests/unit/test_positions.py::TestMapProviderPositionsOutcomeParams::test_partial_failure_built_in_single_call` — partial result built in one call, no mutation.
- `tests/unit/test_positions.py::TestMapProviderPositionsOutcomeParams::test_ok_with_accounts_failed_is_rejected_at_construction` — shared validator runs at construction (impossible combos now rejected).
- `tests/unit/test_server_tool.py::TestPartialFailure::*` (6 tests, new fixture `partial_failure_payload`) — orchestration-level partial failure end to end, including opaque hash and enum membership.

Timestamp propagation guard (assessment item): already pinned by the
existing tests `test_retrieved_at_propagates_to_price_timestamp` (679)
and `test_price_timestamp_matches_retrieved_at` (953); see Deviations.

## Local Verification

- `uv run pytest tests/unit/test_positions.py tests/unit/test_server_tool.py tests/unit/test_results_shared_taxonomy.py -q` → **146 passed**
- `uv run pytest -q` (full suite, commit gate) → **1810 passed, 0 skipped**
- Static sanity: `_compute_unrealized_pl` has exactly one call site; no `unrealizedPL` key is written anywhere in `positions.py`; no post-hoc `pos_result.*` mutations remain; `_detect_account_failures` has no external callers besides `positions.py` and its tests (signature change is internal-only, as the assessment assumed).

## Deviations from Assessment

- **Timestamp test (item 2 of "Tests to add or update")**: no *new* test
  added. At the orchestration level the removed override assigned
  `get_open_positions`' own `utc_now_iso()` value — the same value the
  payload injection propagates — so no external test can distinguish
  override from propagation. The contract is already pinned at mapping
  level by the two existing tests listed above, which stayed green
  through the refactor. Recorded here rather than duplicating them.
- **Slight scope expansion (same file, logged)**: beyond the lines
  explicitly cited, the raw `"provider_error"` / `"transient"` strings
  inside `accounts_failed` entries (unmatched-account list in the
  orchestrator and `_detect_account_failures`) were also switched to
  `AccountFailureDetail` members, and both function docstrings no longer
  list `unrealizedPL` as a payload field. Both follow directly from the
  assessment's "always pass enum members" remediation; no other file or
  behavior touched.

## Follow-ups

- Commit with the affected docs per the constitution gate (full suite
  green, 0 skipped — verified above).
- `docs/tools.md` documents tool **output** contracts only (enum values
  unchanged — `str` enums serialize identically), so no interface doc
  change is required; confirm during review.
- When TD-005/TD-006-style audits continue, `get_open_positions`' audit
  events still emit literal outcome strings (`"ok"`, `"initiated"`, …)
  for event-log fields — left as-is (out of scope; values unchanged).
- Suggested next: `/speckit.bug.test slug=td-007-positions-transform-dry`.