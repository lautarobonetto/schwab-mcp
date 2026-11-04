# Bug Assessment: TD-002 — Outcome/detail taxonomy duplicated across modules (DRY)

- **Slug**: td-002-outcome-taxonomy-duplication
- **Created**: 2026-11-04
- **Source**: pasted text
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

Pasted text (TD-002, tech-debt/refactor report, no URL — nothing fetched). Claims, all verified in source:

- `src/schwab_mcp/transactions.py:144-154` `TransactionOutcome` duplicates `src/schwab_mcp/positions.py:36-42` `OutcomeType` — same four values (`ok`, `partial_failure`, `transient_failure`, `reauth_required`). The transactions docstring (line 148) even claims *"Reused from the positions feature (003)"*, but it is a re-definition.
- `transactions.py:157-169` `TransactionDetail` vs `positions.py:52-61` `DetailType` — overlapping values (`account_failed`, `provider_unreachable`, `reauth_needed`).
- `transactions.py:546-552` `TransactionAccountFailed` vs `positions.py:124-128` `AccountFailed` — near-identical models.
- `transactions.py:653-671` `_validate_cross_rules` vs `positions.py:152-165` `_validate_outcome_rules` — outcome↔field cross-validation rules duplicated with error messages identical word for word ("retryable=True is only allowed when outcome == 'transient_failure'", "partial_failure outcome requires accounts_failed", etc.).

**Refactor proposed by reporter**: shared module `src/schwab_mcp/results.py` holding the outcome enum, shared detail values, `AccountFailed`, and a common outcome-rules validator; both modules import from it and add only feature-specific rules.

**TDD constraint from reporter**: existing model-validation tests must stay green unchanged (behavior preserved); add tests asserting both modules' enums share identity with the shared source.

## Symptom

This is not a runtime defect: the tools behave correctly today. The problem is structural — the "self-classifying result" contract (outcome enum, detail vocabulary, `AccountFailed` payload, and the outcome↔field validation rules) is independently implemented in two feature modules. The docstring in `transactions.py` actively claims reuse where none exists. Expected behavior: one shared definition; drift between the copies is the concrete future risk (e.g., a rule change landing in one validator but not the other).

## Reproduction

Code-inspection reproduction (no runtime repro needed for a DRY finding):

1. Read `src/schwab_mcp/positions.py:36-42` (`OutcomeType`) and `src/schwab_mcp/transactions.py:144-154` (`TransactionOutcome`): same four string values, distinct classes and member casing.
2. Read the two validators: `positions.py:152-165` vs `transactions.py:653-671` — rules 4 (accounts_failed ⇔ partial_failure) and 5 (retryable ⇔ transient_failure) are duplicated with identical error strings. Both trace to the two feature specs: `specs/003-list-open-positions/data-model.md:48` (rule D6) and `specs/006-transaction-history/data-model.md:123` (rule 5), which independently restate the same contracts.
3. Compare the docstring at `transactions.py:148` ("Reused from the positions feature (003)") against the actual code: a re-definition.

[NEEDS CLARIFICATION: none — fully static, verified.]

## Suspected Code Paths

- `src/schwab_mcp/positions.py:36-42` — `OutcomeType` (str, Enum): the original definition (feature 003).
- `src/schwab_mcp/positions.py:52-61` — `DetailType`: 7 values; 3 shared with transactions.
- `src/schwab_mcp/positions.py:64-68` — `AccountFailureDetail` (`provider_error`, `transient`): the closed vocabulary for `AccountFailed.detail`.
- `src/schwab_mcp/positions.py:124-128` — `AccountFailed` model (`detail: AccountFailureDetail`).
- `src/schwab_mcp/positions.py:144-167` — `_validate_outcome_rules` on `PositionsResult`; duplicated rules at 152-155 and 162-165.
- `src/schwab_mcp/transactions.py:144-154` — `TransactionOutcome` (str, Enum): re-definition, values identical, member names lowercase (`ok` vs `OK`).
- `src/schwab_mcp/transactions.py:157-169` — `TransactionDetail`: 6 values; 3 shared with positions, 3 feature-specific (`history_retrieved`, `no_movements`, `no_movements_for_instrument`).
- `src/schwab_mcp/transactions.py:546-552` — `TransactionAccountFailed` (`detail: str` — free-form).
- `src/schwab_mcp/transactions.py:645-683+` — `_validate_cross_rules` on `TransactionsResult`; duplicated rules at 653-671; also feature rule at 746-749 (partial_failure ⇔ detail=account_failed).

### Discrepancies the report missed (found during verification)

1. **`AccountFailed.detail` types differ.** `positions.AccountFailed.detail` is the `AccountFailureDetail` enum; `transactions.TransactionAccountFailed.detail` is a plain `str`. So they are not strictly "near-identical" — the transactions copy is a weaker, untyped re-implementation. In practice `transactions.py:1140-1149` only ever constructs `"transient"` and `"provider_error"` — exactly the enum vocabulary — so adopting the enum is a safe tightening, and tests already pass plain strings (Pydantic coerces str-Enum members by value).
2. **Member-name casing differs.** `OutcomeType.OK` vs `TransactionOutcome.ok`. Tests reference the lowercase names (`tests/unit/test_transactions_models.py:35-53`) and uppercase names in positions tests — the shared enum must support both spellings or tests change (violating the reporter's "tests stay green unchanged" constraint).
3. **The duplication is also rooted in the specs.** Both `specs/003-.../data-model.md` and `specs/006-.../data-model.md` independently restate rules 4/5. Code deduplication alone leaves spec-level duplication; a note in both data-models (or the contracts dir) should mark the shared rule source.

## Root Cause Hypothesis

Feature 006 (transaction history) was built against feature 003's *contract* (same result-shape design language in the two data-models) rather than its *code*, and the implementer re-declared the outcome taxonomy locally instead of extracting a shared module — then documented the intent-to-reuse as if it were actual reuse ("Reused from the positions feature (003)", `transactions.py:148`). Confidence: high (docstring claim contradicts the code; all cited lines verified verbatim).

## Proposed Remediation

**Preferred**: Extract `src/schwab_mcp/results.py` as the single source of the shared result taxonomy, as the reporter suggests, with the verified nuances addressed:

- One `ResultOutcome(str, Enum)` with the four shared values. To keep every existing test green unchanged, expose aliases for both casings (e.g. members `ok/partial_failure/…` plus `OK = ok` aliases), or re-export two namespaced aliases. Both modules import it; `positions.OutcomeType` and `transactions.TransactionOutcome` become aliases of the same class, so `TransactionOutcome.ok is OutcomeType.ok` holds.
- Shared detail values as a base (`account_failed`, `provider_unreachable`, `reauth_needed`) with feature-specific members added in each module (`data_received`, `no_positions`, `store_absent`, `store_corrupted` for positions; `history_retrieved`, `no_movements`, `no_movements_for_instrument` for transactions). Whether this is one enum with all members or per-feature subclasses of a base enum is an implementation decision for `/speckit.bug.fix` — the constraint is that the three shared values have a single definition.
- One `AccountFailed(BaseModel)` with `detail: AccountFailureDetail`; `TransactionAccountFailed` becomes an alias. This tightens transactions from `str` to the enum — behavior-preserving because only `transient`/`provider_error` are ever constructed and tests already pass those strings.
- A shared validator helper (e.g. `validate_shared_outcome_rules(outcome, retryable, accounts_failed) -> None`) enforcing rules 4 and 5 with the exact existing error messages; each `PositionsResult` / `TransactionsResult` `model_validator` calls it first and keeps only its feature-specific rules (positions: empty-positions rule; transactions: empty-movements detail rule, detail=account_failed rule).

**Alternatives**:

- *Minimal dedup only* (share enums + `AccountFailed`, keep both validators): smaller diff, but the worst duplication identified in the report — the word-for-word rule/error duplication — remains.
- *Do nothing / document-only*: record the intentional contract duplication in both data-models. Cheapest, but leaves drift risk and the false docstring; not recommended given the clean seam.

**Files likely to change**:

- `src/schwab_mcp/results.py` (new — shared taxonomy)
- `src/schwab_mcp/positions.py` (import + alias; delete duplicated definitions and rules 4/5 bodies)
- `src/schwab_mcp/transactions.py` (import + alias; same; docstring corrected to state actual reuse)
- `tests/unit/test_results_shared_taxonomy.py` (new — identity tests)
- `docs/tools.md` (only if result-shape wording references module location — verify during fix)

**Tests to add or update**:

- Identity tests: `positions.OutcomeType is schwab_mcp.results.ResultOutcome`-equivalent aliases, same for detail enum base and `AccountFailed`; values preserved (`"ok"`, `"transient"`, …).
- Regression guard: all existing `tests/unit/test_transactions_models.py` and positions model tests pass **unchanged** (the reporter's explicit constraint — makes this a safe refactor).
- Error-message parity test: the two validators raise byte-identical messages for rules 4/5 (prevents future drift).
- Tightening test: `TransactionAccountFailed(detail="nonsense")` now raises (previously accepted free-form `str`) — documents the one intentional behavior change, if the fix adopts the enum.

## Risks & Considerations

- **Test-compat risk (member casing)**: positions tests use `OK`/`PARTIAL_FAILURE`; transactions tests use `ok`/`partial_failure`. A naive shared enum with one casing breaks ~2 dozen existing tests; alias members solve it without touching tests.
- **Behavior tightening**: `TransactionAccountFailed.detail` going `str → enum` rejects values the old model accepted. Currently no producer or test uses values outside the vocabulary, but any external consumer constructing the model with free-form detail would break — flag in the fix and CHANGELOG.
- **Constitution gates**: mandatory TDD (existing-tests-green-unchanged is the red/green harness here); fixed layout (`src/`, `tests/`); docs updated in the same commit; full suite green with 0 skipped before commit.
- **Spec-level duplication remains**: the two data-model.md files still independently restate rules 4/5; the fix should at least cross-reference, and `/speckit.analyze`-style consistency applies to future spec changes.

## Open Questions

- Shared detail enum shape: single enum with all 10 values vs. base + per-feature extension — decide at `/speckit.bug.fix` (identity tests will pin whichever is chosen).
- Whether `docs/tools.md` documents the taxonomy under a path that would change with the new module (verify during fix).