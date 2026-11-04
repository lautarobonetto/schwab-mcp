# Bug Assessment: TD-007 — `positions.py`: transform layer remaps itself (DRY/KISS)

- **Slug**: td-007-positions-transform-dry
- **Created**: 2026-11-04
- **Source**: pasted text (tech-debt report TD-007)
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

Pasted report, TD-007, area `src/schwab_mcp/positions.py`:

> - `unrealized_pl` computed and discarded **three times**: in
>   `_transform_provider_payload` (`655-660`), in the consolidation map
>   (`366-368` — key never read afterwards), and in `PositionEntry`
>   construction (`398-401`, the only one that matters).
> - `_collect_extended` (`286-292`) exists but `_transform_provider_payload`
>   re-implements the same loop inline (`683-686`).
> - Defensive timestamp override (`561-564`) duplicates propagation that
>   already happens via the payload injection (`699-702`) and
>   `map_provider_positions` (`310, 369`) — dead work.
> - Results built with raw strings (`381-384`: `outcome="ok"`,
>   `detail="no_positions"`) instead of the defined enums, and mutated
>   post-hoc on the partial path (`542-545`), bypassing the validator's
>   intent.
>
> **Refactor:** compute `unrealized_pl` once at entry construction; use
> `_collect_extended`; drop the timestamp override; always pass enum
> members and build the final `PositionsResult` in one place (parameterize
> `map_provider_positions` with outcome/detail instead of mutating).
> Related dead params: `_detect_account_failures(..., retrieved_at)`
> (`580`) never uses `retrieved_at`.

## Symptom

Not a functional defect: every computed value ends up correct in the
result. The problem is structural redundancy in the positions pipeline —
the same `unrealized_pl` is computed in three layers where only one is
consumed, an existing helper is bypassed, timestamps are re-assigned with
identical values, and `PositionsResult` fields are set with raw strings
and mutated after construction instead of using the defined
`ResultOutcome`/`DetailType` enums and single-point construction.

## Reproduction

Static finding; no runtime reproduction required.

1. Open `src/schwab_mcp/positions.py`.
2. Observe `_compute_unrealized_pl` call sites: lines 654–659
   (`_transform_provider_payload`), 365–367 (consolidation map), and
   397–400 (`PositionEntry` construction). The `unrealizedPL` key baked
   by the transform layer is never read by `map_provider_positions`, and
   the consolidation map's `unrealized_pl` key is shadowed by a fresh
   recomputation at line 397.
3. Observe the inline extended-field loop at 682–685 duplicating
   `_collect_extended` (285–291).
4. Observe the timestamp override at 560–563 reassigning values that
   already flow through payload injection (700) → `map_provider_positions`
   (309, 368, 401, 422).
5. Observe raw-string literals (`outcome="ok"`, `detail="no_positions"`,
   `outcome="partial_failure"`, `detail="account_failed"`) at 379–385 and
   547–554, and the post-hoc mutation of a validated result at 541–544.
6. Observe `_detect_account_failures(provider_payload, retrieved_at)`
   (579) never referencing `retrieved_at` in its body (call site: 529).

Verified against the working tree — all line references and claims in the
report are accurate.

## Suspected Code Paths

- `src/schwab_mcp/positions.py:654-659` — `_transform_provider_payload`
  computes `unrealizedPL` into the internal payload; `map_provider_positions`
  never reads that key → dead work.
- `src/schwab_mcp/positions.py:365-367` — consolidation map stores
  `unrealized_pl`, but entry construction recomputes it at 397–400 → dead key.
- `src/schwab_mcp/positions.py:397-400` — the only `unrealized_pl` value
  that is consumed (passed to `PositionEntry`).
- `src/schwab_mcp/positions.py:682-685` — inline re-implementation of
  `_collect_extended` (285–291).
- `src/schwab_mcp/positions.py:560-563` — defensive timestamp override in
  `get_open_positions`; duplicates injection/propagation at 700, 309, 368,
  401, 422.
- `src/schwab_mcp/positions.py:379-385, 547-554` — raw strings where
  `ResultOutcome` / `DetailType` enums exist (TD-002 already centralized
  the shared taxonomy in `schwab_mcp.results`).
- `src/schwab_mcp/positions.py:541-544` — post-hoc mutation of a
  `PositionsResult` built by `map_provider_positions`, bypassing
  `validate_shared_outcome_rules`' intent at construction time.
- `src/schwab_mcp/positions.py:579` — `retrieved_at` parameter of
  `_detect_account_failures` is unused (dead param).

## Root Cause Hypothesis

The transform/mapping pipeline accreted defensive and duplicate work as
the feature grew: each layer recomputes or re-asserts values the next
layer already derives, likely from incremental additions (option
multiplier handling, extended passthrough, timestamp propagation) rather
than a single designed pass. All three `unrealized_pl` computations are
currently consistent, so output is correct; the cost is redundancy, drift
risk (a future multiplier/rounding change in one call site but not the
others yields silently inconsistent entries), and obscured data flow.
Confidence: high — every claim was verified by direct source inspection.

## Proposed Remediation

**Preferred**: A single internal restructure of `positions.py`, no
behavior change:

1. **Compute `unrealized_pl` once at entry construction.** Drop the
   `unrealizedPL` key from `_transform_provider_payload` (654–659) and the
   `unrealized_pl` key from the consolidation map (365–367); keep the
   recomputation at `PositionEntry` construction (397–400). Consolidation
   already preserves `market_value` / `average_price` / `quantity` /
   `instrument_type`, which is everything the computation needs.
   Update the docstring of `_transform_provider_payload` to state that
   P/L is not part of the internal payload.
2. **Use `_collect_extended`** in `_transform_provider_payload` (682–685)
   instead of the inline loop.
3. **Drop the timestamp override** (560–563): the payload injection
   (700) → `map_provider_positions` (309, 368, 401, 422) chain already
   propagates `retrieved_at` end to end.
4. **Use enum members everywhere**: `ResultOutcome.OK` /
   `OutcomeType.OK`, `DetailType.NO_POSITIONS`, etc. at 379–385,
   547–554; also the audit-event comparisons at 566–574 can compare
   against enum members for consistency.
5. **Single-point result construction**: parameterize
   `map_provider_positions` (e.g. `outcome: ResultOutcome` and
   `detail: str` / `accounts_failed` / `retryable` kwargs) so the
   partial-failure path builds the final result in one call instead of
   mutating at 541–544. Enum-typed constructor arguments make invalid
   combinations impossible and let `validate_shared_outcome_rules` run
   exactly once at construction.
6. **Remove the dead `retrieved_at` param** from
   `_detect_account_failures` (579) and its call site (529).

**Alternatives**:

- *Minimal patch*: only drop the two dead `unrealized_pl` computations
  and the inline extended loop; leave the timestamp override and raw
  strings. Lower risk, but leaves the mutation pattern and enum debt that
  TD-002 set out to eliminate — not recommended given the file is small
  and well tested.
- *Full mapping-core merge*: fold `_transform_provider_payload` into
  `map_provider_positions` so there is no intermediate payload at all.
  Eliminates the remap entirely but rewrites the tested pure-mapping
  contract (T004, `test_positions.py`) — larger blast radius than the
  debt justifies.

**Files likely to change**:

- `src/schwab_mcp/positions.py`
- `tests/unit/test_positions.py` (notably the test at ~line 1176 which
  asserts `_transform_provider_payload` "bakes the multiplier into
  `unrealizedPL`" — this locks in behavior being removed)

**Tests to add or update**:

- Update the transform-layer test (≈1176–1211) to assert the internal
  payload does **not** carry `unrealizedPL`, and that the option
  multiplier appears only on `PositionEntry.unrealized_pl`.
- Add/update a test asserting entry `price_timestamp` and result
  `retrieved_at` come from the injected payload (guards the removal of
  the override).
- Add a partial-failure test asserting the result is constructed with
  `ResultOutcome.PARTIAL_FAILURE` / `DetailType.ACCOUNT_FAILED` members
  and passes shared-outcome validation without post-hoc mutation.
- Full existing suite (`tests/unit/test_positions.py`,
  `test_results_shared_taxonomy.py`, `test_server_tool.py`) must stay
  green — it is the regression net for this refactor.

## Risks & Considerations

- **Behavioral equivalence must be proven by tests, not assumed**: the
  three computations are consistent today; removing two must not change
  option-multiplier handling (`_compute_unrealized_pl` for options).
- **Locked-in test expectations**: `test_positions.py:1176` asserts the
  transform layer bakes `unrealizedPL` — it will fail until updated; this
  is expected and desirable (constitution: affected tests updated in the
  same commit).
- **Signature changes are internal-only** (`_transform_provider_payload`,
  `_detect_account_failures`, `map_provider_positions`) — confirm no
  external callers exist outside `positions.py` and its tests before
  changing signatures.
- **Enum pass-through**: `OutcomeType`/`DetailType` are `str` enums, so
  serialized output values are unchanged; audit-event consumers relying
  on the literal strings are safe.

## Open Questions

- None blocking. Severity is low because there is no user-visible
  defect; the fix is a pure internal consolidation gated by the existing
  test suite.