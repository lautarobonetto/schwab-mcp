# Bug Fix: Client-shim installation centralized in `build_schwab_client()`

- **Slug**: td-012-client-shim-install
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Moved the trailing-slash callback shim installation inside
`build_schwab_client()` (the declared single construction point) and
deleted the three per-entry-point pre-construction calls, closing the
error class where a future fourth entry point would silently reproduce
the callback-trailing-slash bug. Followed TDD: the lock-in factory test
was written first and failed for the expected reason
(`AttributeError` — the factory did not import the shim) before the
implementation was applied.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/client.py` | modified | Module-level import of `install_trailing_slash_callback_support`; called at the top of `build_schwab_client()` before `schwabdev.Client(...)`; module and function docstrings now state the factory guarantees timeout **and** shim. |
| `src/schwab_mcp/cli.py` | modified | Removed install calls in `run_auth` and `_do_run_renew` (plus their now-orphaned comments) and the module-level import. |
| `src/schwab_mcp/server.py` | modified | Removed install call in `run_serve` (plus comment) and the module-level import. |
| `tests/unit/test_client_factory.py` | added test | `TestClientInstallsTrailingSlashShim` pins the factory-level install via monkeypatch of `schwab_mcp.client.install_trailing_slash_callback_support`. |
| `docs/CHANGELOG.md` | modified | New `Changed` bullet under `[0.9.8]` following the TD-010/TD-011 format. |

## Diff Highlights

`src/schwab_mcp/client.py` — the factory now enforces the shim:

```python
from schwab_mcp.config import Config
from schwab_mcp.schwabdev_compat import install_trailing_slash_callback_support

def build_schwab_client(config, tokens_db, call_on_auth) -> Any:
    """... Every construction is preceded by
    install_trailing_slash_callback_support (idempotent), so no
    entry point needs its own pre-construction ritual ..."""
    install_trailing_slash_callback_support()
    return schwabdev.Client(...)
```

`src/schwab_mcp/server.py` / `src/schwab_mcp/cli.py` — deletions:

```python
- from schwab_mcp.schwabdev_compat import install_trailing_slash_callback_support   # server.py, cli.py
- install_trailing_slash_callback_support()                                        # ×3 sites
```

## Tests Added or Updated

- `tests/unit/test_client_factory.py::TestClientInstallsTrailingSlashShim::test_factory_installs_shim_per_construction` — with `schwabdev.Client` stubbed to `RecordingClient` and the shim monkeypatched with a recording stub, two consecutive `build_schwab_client()` calls must each install exactly once (`["installed", "installed"]`) — proving the install is per-construction inside the factory, not import-time and not per-entry-point.

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_client_factory.py -x -q` (before implementation) → **1 failed** (`AttributeError: module 'schwab_mcp.client' has no attribute 'install_trailing_slash_callback_support'`) — Red for the right reason.
  - `uv run pytest tests/unit/test_client_factory.py tests/unit/test_schwabdev_compat.py -q` (after) → **12 passed** — Green, shim idempotency suite unaffected.
  - `uv run pytest -q` (full suite, commit gate) → **1820 passed, 0 skipped** (was 1819 + 1 new test).
- Manual checks: grep confirms `install_trailing_slash_callback_support` now appears only in `client.py` (import + call + docstring) and its definition in `schwabdev_compat.py` — no call sites left in entry points.
- Lint: no linter is configured in the project environment (`pyproject.toml` defines none; ruff not installed in the venv), so linting was not run.

## Deviations from Assessment

None. The fix follows the assessment's preferred remediation exactly: module-level import in `client.py` (no import cycle — verified), install at the top of the factory, three call sites + two entry-point imports deleted, one lock-in test in `test_client_factory.py`, CHANGELOG updated. The assessment's test suggestion was realized as a single test covering both one-call-per-construction and repeatability (two builds) rather than two separate tests.

## Follow-ups

- None required. Optional future consideration: if a fifth construction path ever bypasses `build_schwab_client()`, the factory test would not catch it — but the module docstring and the "single source of truth" contract make that a review-visible violation.