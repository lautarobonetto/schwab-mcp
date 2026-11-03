# Bug Fix: `$SPX` + `delta_target` timeout — configurable provider request timeout via shared client factory

- **Slug**: spx-delta-timeout
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

All three `schwabdev.Client` construction sites (`serve`, `auth`, `renew`) now build the client
through a shared factory, `schwab_mcp.client.build_schwab_client`, which forwards
`timeout=Config.request_timeout` — eliminating schwabdev's 10 s default that broke `$SPX` +
`delta_target` fetches. The timeout is configurable via the new `SCHWAB_MCP_REQUEST_TIMEOUT`
environment variable (positive integer seconds, default 60) and fails fast on invalid values.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/client.py` | added | Shared factory `build_schwab_client(config, tokens_db, call_on_auth)` — single construction point (DRY); `schwabdev.Client` resolved at call time so tests can monkeypatch it |
| `src/schwab_mcp/config.py` | modified | `Config.request_timeout: int = 60`; env `SCHWAB_MCP_REQUEST_TIMEOUT` parsed and validated (integer, > 0 → else `InvalidConfigError`) |
| `src/schwab_mcp/server.py` | modified | `run_serve` builds the client via the factory; late-import kept for patchability; `ValueError` → `InvalidConfigError` mapping preserved |
| `src/schwab_mcp/cli.py` | modified | `run_auth` and `_do_run_renew` build the client via the factory; module-level `import schwabdev` retained (tests patch `schwab_mcp.cli.schwabdev.Client`, which resolves to the same shared module object) |
| `tests/unit/test_config.py` | added tests | `TestRequestTimeout` — default 60, custom value, whitespace stripping, zero/negative/non-integer/empty → `InvalidConfigError` |
| `tests/unit/test_client_factory.py` | added | Factory contract: positional credentials, `tokens_db`, `call_on_auth`, `open_browser_for_auth=False` forwarded; `timeout` equals configured value; default is 60 |
| `tests/integration/test_serve.py` | modified + added tests | `FakeSchwabdevClient` records the `timeout` kwarg; `_default_env` isolates the env var; `TestClientRequestTimeout` pins env override (90) and default (60) end-to-end through `cli_main(["serve"])` |
| `docs/installation.md` | modified | Env-var table row for `SCHWAB_MCP_REQUEST_TIMEOUT` |
| `specs/001-schwab-oauth-access/contracts/configuration.md` | modified | Env-var row + validation rule 4 (fail fast on invalid timeout) |
| `docs/CHANGELOG.md` | modified | `[0.9.3]` Fixed entry referencing bug `spx-delta-timeout` |
| `pyproject.toml` | modified | Version bump 0.9.2 → 0.9.3 (project's established bug-release pattern) |

## Diff Highlights

`src/schwab_mcp/client.py` (new, core of the fix):

```python
def build_schwab_client(config, tokens_db, call_on_auth):
    return schwabdev.Client(
        config.app_key,
        config.app_secret,
        config.callback_url,
        tokens_db=tokens_db,
        call_on_auth=call_on_auth,
        open_browser_for_auth=False,
        timeout=config.request_timeout,
    )
```

`src/schwab_mcp/config.py` (validation, fail fast):

```python
if raw_timeout is None:
    request_timeout = _DEFAULT_REQUEST_TIMEOUT
else:
    try:
        request_timeout = int(raw_timeout.strip())
    except ValueError:
        raise InvalidConfigError(
            detail=(f"{_ENV_REQUEST_TIMEOUT} must be an integer number of "
                    f"seconds, got {raw_timeout.strip()!r}")) from None
    if request_timeout <= 0:
        raise InvalidConfigError(...)
```

## Tests Added or Updated

- `tests/unit/test_config.py::TestRequestTimeout` — env parsing + fail-fast validation (7 cases).
- `tests/unit/test_client_factory.py` — factory forwards all construction args and the configured
  `timeout` (regression pin: the missing kwarg was the defect).
- `tests/integration/test_serve.py::TestClientRequestTimeout` — end-to-end through
  `cli_main(["serve"])`: env override reaches the client constructor; unset env yields the 60 s
  default (not schwabdev's 10 s).

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_config.py::TestRequestTimeout tests/unit/test_client_factory.py …` → red first (`ModuleNotFoundError: schwab_mcp.client`), green after implementation.
  - `uv run pytest -q` (full suite, commit gate) → **1703 passed, 0 skipped**.
- Manual checks: confirmed `schwabdev.Client.__init__(…, timeout: int = 10, …)` signature before the
  change (the root cause from the assessment); confirmed the factory's call-time
  `schwabdev.Client` attribute resolution keeps all existing monkeypatch styles working
  (`"schwabdev.Client"` and `"schwab_mcp.cli.schwabdev.Client"` both resolve to the same module).

## Deviations from Assessment

- **Scope addition: version bump + CHANGELOG entry** (`pyproject.toml`, `docs/CHANGELOG.md`). The
  assessment listed only config/factory/tests/docs; the project's release pattern (0.9.1, 0.9.2)
  ships every bug fix as a patch bump with a CHANGELOG `Fixed` entry, and the release tests pin
  pyproject version against the CHANGELOG top section — so the bump was required to keep the suite
  green.
- **`cli.py` module-level `import schwabdev` retained** instead of removed: `tests/integration/`
  patches `schwab_mcp.cli.schwabdev.Client`, which requires the module-level import to exist. The
  attribute resolves to the shared `schwabdev` module, so the factory still picks up the patch.
- **Optional fetch-timeout unit test skipped**: the assessment marked it "optional"; `retry_call`
  → `ConnectivityError` wrapping is already covered by `tests/unit/test_tokens.py` (multiple
  cases), so adding a duplicate would violate DRY.

## Follow-ups

- Bug 2 from the same live run (domain errors swallowed at the MCP boundary — callers only see
  "Error executing tool …") is still open; triage it separately.
- Issue 3 (silent `expiration_date` DTE>60 omission) and Issue 4 (undocumented `settlement_type` "A")
  remain open.
- The `retry_call` message "Schwab API unreachable **after retry**" is misleading for `retries=0`
  call sites (see assessment's correction); consider rewording when `tokens.py` is next touched.
- If `$SPX` fetches at `strikeCount=200` still approach 60 s on some links, consider measuring the
  actual duration (assessment open question) and revisiting `DELTA_STRIKE_COUNT_CEILING`.