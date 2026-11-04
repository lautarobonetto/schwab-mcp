# Bug Verification: TD-003 — SQLite token-store read triplicated (DRY)

- **Slug**: td-003-token-store-read-duplication
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The duplication no longer reproduces: the store-read block and the identical
`SELECT expires_in, access_token_issued, refresh_token_issued FROM schwabdev
LIMIT 1` query each exist exactly once in `src/` (inside
`tokens._read_schwabdev_row`), and `peek_store` is fully deleted. All new,
updated, and targeted regression tests pass; the full suite is green except
two failures proven pre-existing and unrelated to this fix.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | `grep -rn "mode=ro" src/` and `grep -rn "access_token_issued, refresh_token_issued" src/` | pass | Exactly one `mode=ro` connect and one identical query in `src/` — both inside the helper (`tokens.py:103`, `tokens.py:109`). Assessment's static repro (3 copies) no longer holds. |
| `peek_store` fully removed | `grep -rn "peek_store\b" src/ tests/` (excluding `peek_store_status`) | pass | Zero code references; only comments/docstrings remain (incl. the known stale prose at `tests/integration/test_failures.py:449,460`, recorded as a fix follow-up). `.pyc` cache hits are build artifacts. |
| New / updated tests | `uv run pytest tests/unit/test_tokens.py -q` | pass | 41 passed — `TestReadSchwabdevRow` (tri-state), `TestStoreReadEquivalence`, and the untouched `TestPeekStoreStatus` suite. |
| Regression: `read_store_lifetime` | `uv run pytest tests/unit/test_renewal.py -q` (in combined run) | pass | `TestStoreLifetimeReader` (17 equivalence tests) green unchanged. |
| Regression: auth flow | `uv run pytest tests/integration/test_auth.py tests/integration/test_failures.py tests/integration/test_serve.py -q` | pass | 133 passed across the combined targeted run (with `test_renewal.py`). |
| Full suite (commit gate) | `uv run pytest -q` | pass | 1772 passed, 2 failed — both failures are the pre-existing, unrelated `TestDteCeiling` cases (proven to fail on the stashed base tree during the fix phase; tied to uncommitted `dte_max` work). |
| Lint / type-check | — | not-run | No lint or type-check tooling configured in `pyproject.toml` (only pytest/setuptools sections). |

## Output Excerpts

```
$ uv run pytest tests/unit/test_tokens.py -q
.........................................                                [100%]
41 passed in 4.18s

$ uv run pytest tests/unit/test_renewal.py tests/integration/test_auth.py \
    tests/integration/test_failures.py tests/integration/test_serve.py -q
.............................................................            [100%]
133 passed in 6.54s

$ uv run pytest -q
2 failed, 1772 passed in 34.68s
FAILED tests/unit/test_option_expirations.py::TestDteCeiling::test_dte_max_30_...
FAILED tests/unit/test_option_expirations.py::TestDteCeiling::test_dte_max_365_...
```

## Residual Risks

- The two `run_auth` gate sites now treat a *corrupted* store differently than
  the deleted `peek_store` did (old bool collapsed corrupted → "missing").
  This is unreachable in practice (quarantine at `cli.py:103`; store moved
  aside by `backup_token_store` at `cli.py:128` before both gates) and is
  pinned by `test_auth_gate_expression_semantics`, but any future code path
  that reaches those gates with a corrupted store will observe the new
  semantics.
- The full-suite gate is not fully green due to the pre-existing
  `TestDteCeiling` failures — they must be resolved (separately) before this
  change is committed, per the constitution's commit gate.
- No lint/type-check layer exists, so style/type regressions would only
  surface via tests.

## Recommendation

Close the bug — the DRY violation no longer reproduces (verified statically),
the consolidated helper is pinned by tri-state and equivalence tests, and no
regressions were introduced. Before committing: mark TD-003 resolved in
`docs/tech-debt.md`, add the CHANGELOG entry, and address the pre-existing
`TestDteCeiling` failures so the commit gate is fully green.
