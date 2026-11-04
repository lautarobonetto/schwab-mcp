# Bug Assessment: Client-shim installation scattered across entry points (DRY)

- **Slug**: td-012-client-shim-install
- **Created**: 2026-11-04
- **Source**: pasted text (TD-012 report)
- **Verdict**: valid (latent defect — no live failure today, open error class)
- **Severity**: medium

## Report (verbatim or summarized)

TD-012 — `install_trailing_slash_callback_support()` is called at three
sites (`cli.py:149, 321`, `server.py:124` per the report; verified current
lines `cli.py:150, 325`, `server.py:125`) before every `schwabdev.Client`
construction, but `client.py:24-54` (`build_schwab_client()`) is already
the declared single construction point. Forgetting the install at a
future fourth entry point silently reproduces the callback-trailing-slash
bug. Proposed refactor: move installation inside `build_schwab_client()`
(it is idempotent — `schwabdev_compat.py:71-72`).

## Symptom

Not a runtime failure today: every current construction site pairs
`install_trailing_slash_callback_support()` with a
`build_schwab_client()` call. The defect is structural — the shim
installation lives in the entry points instead of the factory, so the
factory's "single source of truth" guarantee does not actually cover the
trailing-slash relaxation, and a future entry point (or a call reordered)
that builds a client without the install silently re-exposes the original
bug: a callback URL with a portal-required trailing `/` fails schwabdev's
`redirect_uri` validation.

## Reproduction

This is a latent defect; no reproducible failure exists in `main` today
(all 3 construction sites are correctly paired). The failure mode is:

1. Add a new entry point (e.g. a `rotate` or headless command) that calls
   `build_schwab_client()` directly, following `client.py`'s "every entry
   point constructs the client the same way" contract.
2. Omit `install_trailing_slash_callback_support()` — nothing forces it;
   no test fails.
3. Run the command with a callback URL configured with a trailing `/`
   (portal-required spelling): schwabdev rejects the `redirect_uri` at
   authorization. [NEEDS CLARIFICATION: exact user-visible error text in
   that scenario — inferred from `schwabdev_compat.py` docstrings, not
   observed.]

## Suspected Code Paths

- `src/schwab_mcp/client.py:24-54` — `build_schwab_client()`: the declared
  single construction point ("single source of truth" in the module
  docstring) that does **not** install the shim.
- `src/schwab_mcp/cli.py:150` — install before build in `run_auth`
  (build at `cli.py:153`).
- `src/schwab_mcp/cli.py:325` — install before build in `_do_run_renew`
  (the explicit `renew` command; build at `cli.py:329`).
- `src/schwab_mcp/server.py:125` — install before build in `run_serve`
  (build at `server.py:132`).
- `src/schwab_mcp/schwabdev_compat.py:54-144` — the shim itself;
  idempotency verified at lines 70-72 (`_SHIM_MARKER` early return),
  matching the report's claim.

Graph evidence: both `install_trailing_slash_callback_support` and
`build_schwab_client` have the same 6 inbound caller set
(`cli.run_auth`, `cli._do_run_renew`, `cli.run_renew`, `cli._run_serve_command`,
`server.run_serve`, server module) — every client construction already
routes through the factory, so moving the install there loses no call
site. All claims verified against source (graph mixes CALLS/MENTIONS).

## Root Cause Hypothesis

The factory (`build_schwab_client`) was introduced (bug `spx-delta-timeout`)
to centralize construction, but the trailing-slash shim predates or
evolved separately and its installation was left at the entry points as a
pre-construction ritual. The result is one piece of knowledge ("a client
must have the shim installed") implemented in three places — a DRY
violation (Constitution II/III) that keeps the trailing-slash error class
open: correctness depends on every future entry point remembering the
ritual instead of the factory enforcing it. Confidence: **high** — all
call sites and the idempotency guard were read directly.

## Proposed Remediation

**Preferred**: move the install inside the factory. In
`src/schwab_mcp/client.py`, import
`install_trailing_slash_callback_support` from
`schwab_mcp.schwabdev_compat` at module level (no cycle:
`schwabdev_compat` does not import `client`) and call it at the top of
`build_schwab_client()`, before `schwabdev.Client(...)`. Update the
module docstring to state that the factory guarantees both the request
timeout **and** the trailing-slash callback support. Then delete the
three call sites — `cli.py:150`, `cli.py:325`, `server.py:125` — and the
now-unused imports (`cli.py:25`, `server.py:28`). The shim is idempotent
(`schwabdev_compat.py:70-72`), so multiple factory calls in one process
(serve → renew handoff) are safe. Keep the top-of-function call rather
than an import-time side effect so `client.py` remains importable for
tests without mutating `schwabdev.tokens`.

To keep the install observable in tests, the factory-level import should
stay a plain module attribute (monkeypatchable as
`schwab_mcp.client.install_trailing_slash_callback_support`), matching
the existing testability pattern used by the late imports in `cli.py`.

**Alternatives** (optional):
- Install at `schwabdev_compat` import time: one line total, but an
  import-time global monkey-patch of the real library violates the
  project's patchability/testability conventions and fires for every
  process that merely imports the module. Rejected.
- Keep entry-point installs and add a test that fails if a
  `build_schwab_client` call site lacks a preceding install: brittle
  source-grepping test, does not close the error class, still one
  implementation per call site. Rejected.

**Files likely to change**:
- `src/schwab_mcp/client.py` (install inside factory + docstring)
- `src/schwab_mcp/cli.py` (remove 2 installs + 1 import)
- `src/schwab_mcp/server.py` (remove 1 install + 1 import)
- `tests/unit/test_client_factory.py` (new lock-in test)
- `docs/CHANGELOG.md` (per commit gate: affected docs in same commit)

**Tests to add or update**:
- `tests/unit/test_client_factory.py`: new test asserting that
  `build_schwab_client()` installs the shim — monkeypatch
  `schwab_mcp.client.install_trailing_slash_callback_support` with a
  recording stub and assert exactly one call per construction (with
  `RecordingClient` so no real client is built).
- Keep `tests/unit/test_schwabdev_compat.py` as-is: it already locks
  idempotency and the RuntimeError paths.
- Full-suite green with 0 skipped per the commit gate (removal of the
  three call sites must not break entry-point tests — none reference the
  shim directly today, verified by grep in `tests/`).

## Risks & Considerations

- **Test isolation**: once the factory installs the shim, factory unit
  tests mutate the real `schwabdev.tokens.Tokens` class (global
  monkey-patch). Harmless for `RecordingClient`-based tests and already
  exercised by `test_schwabdev_compat.py`, but the monkeypatched-stub
  test above keeps the factory test hermetic.
- **Ordering**: the install must remain strictly before construction —
  inside the factory this is guaranteed by construction, which is the
  point of the fix.
- **No API breakage**: internal refactor only; no public interface or
  contract changes (`specs/*/contracts/` unaffected).
- **Observability**: no behavior change on happy path; a future
  incompatible schwabdev release still fails loudly via the shim's
  `RuntimeError`, now from inside the factory.

## Open Questions

- None blocking. The report's cited line numbers were slightly stale
  (`cli.py:149, 321`, `server.py:124` vs. verified `150, 325, 125`) but
  point to the exact sites; no clarification needed.