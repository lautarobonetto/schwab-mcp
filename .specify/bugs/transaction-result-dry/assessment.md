# Bug Assessment: TD-005 — Result construction repeated in `get_transaction_history` (DRY)

- **Slug**: transaction-result-dry
- **Created**: 2026-11-04
- **Source**: pasted text (TD-005 tech-debt report)
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

Pasted report TD-005 claims that the ~330-line orchestrator
`get_transaction_history` in `src/schwab_mcp/transactions.py:939-1272`
repeats result construction in several places:

- Identical reauth result blocks ×2 and transient result blocks ×2, plus a
  duplicated `__cause__` inspection.
- Two `partial_failure` branches that produce **exactly the same result**
  when there are no successes, making the first branch "dead code in
  disguise".
- The "ok, no movements" result built twice, including duplicated
  detail/event computation.
- `PAGE_SIZE = 50` as a local constant in the function, hard-coded again in
  the model validator and its field description.
- A redundant condition (`filter_match_count is not None` ⟺
  `symbol is not None` at that point).
- Validator rule 7 parses `occurred_at` dates twice.

Proposed refactor: `_reauth_result` / `_transient_result` /
`_empty_ok_result(...)` helpers, one shared `ConnectivityError` handler,
module-level `PAGE_SIZE`, delete the dead `partial_failure` branch, extract
`_paginate(...)` and `_fetch_account_movements(...)` so the orchestrator
drops to ~80 lines.

## Symptom

No functional defect: the tool returns correct results in every case. The
"bug" is maintainability debt — the same result-construction knowledge is
implemented in 2–4 places each, so any future edit to one copy (fields,
details, pagination semantics) risks divergence from its twins. Confidence
in the duplication claims: verified directly against source.

## Reproduction

1. Open `src/schwab_mcp/transactions.py` and inspect
   `get_transaction_history` (spans lines 931–1264, ~333 lines).
2. Compare the reauth blocks at 1012–1017 vs 1114–1119 and the transient
   blocks at 1021–1026 vs 1124–1129 — identical `TransactionsResult`
   constructions.
3. Trace the no-success path: if no account succeeds, `all_movements == []`
   yields `_total=0, _page=[], _returned=0, _has_more=False,
   _next_offset=None` — exactly what the first `partial_failure` branch
   hardcodes, so the two branches are output-equivalent.

No runtime reproduction needed; this is verified by code inspection.

## Suspected Code Paths

Note: the report's line numbers are shifted ~8 lines from current source;
actual lines below.

- `src/schwab_mcp/transactions.py:931-1264` — `get_transaction_history`, the
  ~333-line orchestrator named in the report.
- `src/schwab_mcp/transactions.py:1009-1026` — `__cause__` inspection +
  reauth/transient result construction after `linked_accounts()` fails.
- `src/schwab_mcp/transactions.py:1110-1136` — same `__cause__` inspection
  and reauth/transient construction duplicated inside the per-account loop
  (the transient return there is additionally guarded by `has_any_success`;
  result *construction* is identical, classification logic differs).
- `src/schwab_mcp/transactions.py:1029-1048` and `:1215-1243` — "ok, no
  movements" result built twice (no accounts; filtered to empty), with
  duplicated detail/event computation.
- `src/schwab_mcp/transactions.py:1183-1213` — the two `partial_failure`
  branches; output-equivalent in the no-success case (verified arithmetically
  above), so a single `if failed_accounts:` branch suffices.
- `src/schwab_mcp/transactions.py:1160` — local `PAGE_SIZE = 50`;
  hard-coded again at `:691` (`returned != 50` in validator rule 2) and in
  the field description at `:633` ("<= 50").
- `src/schwab_mcp/transactions.py:1223` — redundant conjunction
  `symbol is not None and filter_match_count is not None`:
  `filter_match_count` is set iff `symbol is not None` (lines 1163–1170).
- `src/schwab_mcp/transactions.py:701-712` — validator rule 7 parses each
  `occurred_at` in the `try` block and again in the `else` block.

## Root Cause Hypothesis

The orchestrator grew outcome-by-outcome (each auth-event + result block
written inline next to the classification logic) instead of centralizing
result construction, so identical `TransactionsResult` literals and the
cause-classification pattern were copy-pasted per site. This is a structural
issue, not a logic defect — the duplicates are currently consistent.
Confidence: high (all eight claims verified by direct source inspection;
none contradicted).

## Proposed Remediation

**Preferred**: Pure refactor of `src/schwab_mcp/transactions.py`, no
behavioral change:

1. Module-level `PAGE_SIZE = 50`; reference it from the paginator, validator
   rule 2 (`:691`), and the field description (`:633` — build the string with
   an f-string or keep the literal but add a test pinning consistency).
2. Helpers `_reauth_result(retrieved_at)` and
   `_transient_result(retrieved_at)` replacing the four duplicated blocks;
   one shared `ConnectivityError` classifier that inspects `__cause__` once
   and returns an outcome (reauth / transient / provider_error), used by
   both the `linked_accounts()` site and the per-account loop (the loop's
   `has_any_success` guard stays at the call site).
3. Delete the first `partial_failure` branch and collapse to a single
   `if failed_accounts:` branch — the computed page values equal the
   hardcoded ones when `has_any_success` is false (verified above).
4. `_empty_ok_result(retrieved_at, offset, symbol)` for the two "ok, no
   movements" sites, centralizing the detail/event computation.
5. Extract `_paginate(movements, offset)` and, if it keeps the orchestrator
   readable, `_fetch_account_movements(...)`; target ~80-line orchestrator.
6. In validator rule 7, parse each `occurred_at` once (collect parsed dates
   in the `try`, compare in the `else`).

The existing behavioral suite in `tests/unit/test_transactions_query.py`
and `tests/unit/test_transactions_filter_query.py` is the safety net: it
already locks ok/no_movements, transient, reauth, and partial_failure (both
some-fail and all-fail variants, per `:684` and filter variant `:1279`).
Per the constitution this is a Red→Green→Refactor where Red is already
green — the refactor must keep the full suite green with zero skipped tests.

**Alternatives**:
- Leave as-is and only fix the highest-risk duplication (module-level
  `PAGE_SIZE` + single `partial_failure` branch). Trade-off: cheaper, but
  leaves the four reauth/transient copies that are the likeliest divergence
  point.
- Replace inline construction with a generic result factory keyed by
  outcome. Trade-off: over-abstracted for three call shapes; violates KISS
  relative to three small named helpers.

**Files likely to change**:
- `src/schwab_mcp/transactions.py`
- `tests/unit/test_transactions_query.py` (only if a PAGE_SIZE-consistency
  pin is added; otherwise unchanged)
- `docs/tools.md` / `docs/CHANGELOG.md` — only if the refactor is user-
  observable (it should not be); CHANGELOG entry per commit policy.

**Tests to add or update**:
- No new behavioral tests strictly required — existing suite covers every
  outcome class touched by the refactor (including
  `test_all_accounts_fail_returns_partial_failure`, which pins the
  branch-collapse).
- Optional pin: assert `PAGE_SIZE` module constant equals the `50` used in
  validator rule 2, guarding against future divergence.

## Risks & Considerations

- **Behavioral regression in branch collapse**: the `partial_failure`
  merge must keep the `has_any_success` guard semantics; a wrong merge
  could return `ok/no_movements` when all accounts fail. The existing
  all-fail test catches this.
- **Validator change (rule 7 double-parse)** touches a cross-field rule —
  unparseable-date fixtures rely on the skip-on-`ValueError` behavior; keep
  that contract intact.
- **Pure refactor, no API change**: no MCP contract, migration, or
  performance risk expected; pagination behavior is already test-locked.
- Constitution gates apply: full suite green, affected docs updated in the
  same commit.

## Open Questions

- None blocking. Whether to extract `_fetch_account_movements(...)` vs.
  stopping at the result helpers is a taste call for `/speckit.bug.fix` —
  KISS favors the smallest extraction that reaches the ~80-line target.