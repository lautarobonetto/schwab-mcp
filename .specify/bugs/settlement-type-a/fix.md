# Bug Fix: Document the full observed settlement_type value set (C/P/A/B)

- **Slug**: settlement-type-a
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

The assessment's documentation-first remediation was applied: the
`settlement_type` contract now enumerates the full observed provider set
(`C`, `P`, `A`, `B`) and marks it **non-exhaustive** pass-through, with
`A`/`B` both described as AM (open) index settlement. A new unit test
pins `B` (and, implicitly, any unknown letter) passing through
unmodified. No production code changed — the pass-through design was
correct; only the documented value enumeration and its consumers'
guidance were wrong.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `docs/tools.md` | modified | `settlement_type` bullet (get_option_expiration_chain §Output schema) now lists `C`/`P`/`A`/`B` with the non-exhaustive, never-branch-on-a-closed-enum instruction; agent-guidance item 4 adds "treat `A` and `B` as AM settlement, never reject an unknown letter" |
| `specs/012-option-expiration-list/data-model.md` | modified | §2 field table row updated with the same enumeration + non-exhaustive wording |
| `specs/012-option-expiration-list/research.md` | modified | R2 provider-field description now shows the observed set including `B` |
| `specs/012-option-expiration-list/quickstart.md` | modified | AM/PM example note extended with the `A`/`B` labeling |
| `tests/unit/test_option_expirations.py` | added test | `test_settlement_type_b_passes_through_unmodified` in `TestCuratedFieldMapping` |
| `docs/CHANGELOG.md` | modified | entry added to the unreleased `[0.9.6]` section (constitution: affected docs in the same commit) |

## Diff Highlights

`docs/tools.md` (Output schema bullet, before → after):

```diff
-- `settlement_type` passes through verbatim (`C` close-settled,
-  `P`/`A` PM/AM index settlement); explicit `null` when the provider omits
-  it. ...
+- `settlement_type` passes through verbatim; ...
+  **Observed values — non-exhaustive; never branch on a closed enum:**
+  `C` close-settled (equities), `P` PM index settlement, `A` and `B`
+  AM (open) index settlement. ... An unknown letter surfaces verbatim.
```

New test (tests/unit/test_option_expirations.py):

```python
def test_settlement_type_b_passes_through_unmodified(self) -> None:
    payload = build_expiration_chain_payload([("2026-11-20", 17, "B")])
    result = build_expiration_result(payload, _query(), TODAY)
    assert result["expirations"][0]["settlement_type"] == "B"
```

## Tests Added or Updated

- `tests/unit/test_option_expirations.py::TestCuratedFieldMapping::test_settlement_type_b_passes_through_unmodified`
  — pins that a `settlementType: "B"` provider entry (the live value
  observed on SPX near-term standard monthlies) surfaces as `settlement_type:
  "B"` verbatim, never dropped or rewritten.

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_option_expirations.py -q` → **34 passed** (includes the new `B` test)
  - `uv run pytest tests/unit -q` → **1436 passed, 0 skipped** (commit-gate unit scope)
- Manual checks: live `get_option_expiration_chain` on `$SPX` (dte_max=365) was
  re-confirmed during assessment — `P`×35, `B`×5, `A`×7 — matching the documented
  enumeration now written down. Integration suite (network-dependent) not run,
  per guardrail.

## Deviations from Assessment

- `docs/CHANGELOG.md`: the assessment listed it under "Files likely to change";
  the concrete placement (the unreleased `[0.9.6]` section, which already holds
  today's uncommitted `option-chain-dte-filter` entry) was a judgment call not
  specified in the assessment.
- No other deviations: the remediation's preferred path (documentation +
  pass-through test, no code normalization) was followed exactly, and all edits
  stayed within the files the assessment listed.

## Follow-ups

- The `B` letter's exact provider semantics remain an open question from the
  assessment (near-term-monthly labeling vs `optionRoots: "SPX, SPXW"`
  co-listing artifact). If Schwab ever documents `settlementType`, revisit the
  `A`/`B` wording in `docs/tools.md`.
- The `$SPX` live observation was made 2026-11-03 with dte_max=365; the
  B→A boundary (2027-03/2027-04 monthlies) may drift as time passes — the
  non-exhaustive wording is deliberately date-agnostic about the split.