# Bug Verification: Client-shim installation centralized in `build_schwab_client()`

- **Slug**: td-012-client-shim-install
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The bug does not reproduce post-fix: a simulated "fourth entry point"
that constructs a client through `build_schwab_client()` alone — with no
pre-construction shim ritual — ends up with the trailing-slash shim
installed, which is exactly the scenario the assessment identified as
the open error class. No regressions: full suite green.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | Inline script: stub `schwabdev.Client`, call `build_schwab_client()` directly (no `install_trailing_slash_callback_support()` anywhere), assert `_schwab_mcp_trailing_slash_shim` marker present on `schwabdev.tokens.Tokens.__init__` and `timeout` forwarded | pass | Automated equivalent of the assessment's latent reproduction ("future fourth entry point calls the factory without the ritual"). Pre-fix this fails; post-fix the shim is installed by the factory itself. |
| New / updated tests | `uv run pytest tests/unit/test_client_factory.py tests/unit/test_schwabdev_compat.py -q` | pass | Includes the fix's lock-in test `TestClientInstallsTrailingSlashShim::test_factory_installs_shim_per_construction` and the shim's behavioral suite (idempotency, trailing-slash tolerance, RuntimeError paths). |
| Regression suite | `uv run pytest -q` (full suite, commit gate) | pass | 1820 passed, 0 skipped (1819 pre-fix + 1 new test). |
| Lint / type-check | — | not-run | No linter or type-checker is configured in the project environment (`pyproject.toml` defines none; ruff/mypy not installed in the venv). |

## Output Excerpts

Reproduction-equivalent script:

```
OK: factory-only construction installed the trailing-slash shim
(pre-fix this would reproduce TD-012)
```

Targeted tests:

```
............                                                             [100%]
12 passed in 0.19s
```

Full regression suite:

```
....................                                                     [100%]
1820 passed in 34.29s
```

## Residual Risks

- The reproduction-equivalent asserts the shim is **installed** (marker
  check) rather than driving a real authorization flow against
  Schwab's API; the shim's *behavioral* correctness (trailing-slash
  tolerance, exact-callback restoration, in-init flow) is covered by
  `tests/unit/test_schwabdev_compat.py`, which passed unchanged. A live
  end-to-end auth with a portal callback URL ending in `/` was not run
  (network-dependent) — behavior is unchanged on the happy path, so this
  matches the assessment's "behavior-preserving" claim.
- The original symptom was latent (no live failure existed on `main`
  pre-fix); "verified" here means the error class is closed and
  behavior is preserved, not that a runtime failure was observed and
  eliminated.

## Recommendation

Close the bug — the factory now structurally guarantees the shim
installation (timeout + trailing-slash support are both enforced in
`build_schwab_client()`), the latent-reproduction scenario no longer
reproduces, and the full suite is green with the new lock-in test in
place. Commit may proceed per the constitution gate (suite green, 0
skipped, docs updated in the same commit — already in `fix.md`'s change
set).