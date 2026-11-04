# Bug Verification: Release — member list hardcoded twice in `allowlist.py` (DRY)

- **Slug**: td-014
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The duplication no longer reproduces: the member list exists exactly once in
`allowlist.py` (the `_CONTENT_MEMBER_TABLE`), and a desync probe proved the
new invariant test fails loudly for both one-sided-member directions. Full
regression suite green (1821 passed, 0 skipped); no regressions found.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | re-read `src/schwab_mcp_release/allowlist.py` + `grep` for member-path literals | pass | Each member path literal (`docs/release/…`, `install.sh`, wheel) appears exactly once, inside `_CONTENT_MEMBER_TABLE`; `member_specs()` and `source_map()` only derive from it. The assessment's reproduction (two hardcoded lists at lines 44–60 vs 68–79) no longer holds. |
| Desync-catch probe (both failure modes) | `uv run pytest tmp/td014_desync_probe.py -q` (scratch, git-ignored) | pass | Monkeypatching `source_map` (silent direction) or `member_specs` (loud direction) with one extra member makes the invariant assertion `set(source_map(...)) == {spec.path for spec in content_members(...)}` raise `AssertionError`; intact code passes. Both bug failure modes are now caught in the suite. |
| New / updated tests | `uv run pytest tests/unit/test_release_allowlist.py -q` | pass | 43 passed, including `test_source_map_covers_exactly_the_content_members`. |
| Regression suite | `uv run pytest -q` | pass | 1821 passed, 0 skipped — commit gate green. |
| Lint / type-check | — | not-run | No lint or type-check tooling configured in `pyproject.toml` (only pytest + setuptools). |

## Output Excerpts

- `tests/unit/test_release_allowlist.py` → `43 passed in 0.09s`
- `tmp/td014_desync_probe.py` → `3 passed in 0.01s`
- Full suite → `1821 passed in 33.25s`

Probe note (honest record): the first probe draft tested adding/removing a
row to `_CONTENT_MEMBER_TABLE` itself and expected the invariant to fail —
it didn't, because with the single table both derivations change together
(i.e., the refactor makes that scenario impossible by construction). The
probe was redesigned to patch the derived functions, which is the bug's real
failure mode; it then failed the invariant as expected. The fix held; the
initial probe design was wrong.

## Residual Risks

- The invariant test guards the *derivation*; nothing stops a future edit
  that bypasses both (e.g., a new caller building its own dict) — out of
  scope for this bug.
- `tmp/td014_desync_probe.py` is a scratch probe (git-ignored) and is not
  part of the suite; its monkeypatching style is intentionally not promoted
  to `tests/`.

## Recommendation

Close the bug — the duplication is eliminated, both desync directions are
locked behind the suite, and the full regression gate is green. Remaining
step per the constitution: commit with the suite green and no skipped tests
(no doc updates required; the module docstring's DRY claim is now accurate).