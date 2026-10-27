# Tasks: Schwab OAuth Access

**Input**: Design documents from `/specs/001-schwab-oauth-access/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Test tasks ARE included. The project constitution (Principle I) makes TDD non-negotiable: every test task must be completed and observed FAILING before its corresponding implementation task begins. No production code without a preceding failing test.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `src/schwab_mcp/` and `tests/` at repository root (constitution Repository Layout: all source in `src/`, all tests in `tests/`, docs in `docs/`, scratch in `tmp/`)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 Create directory structure per plan.md: `src/schwab_mcp/`, `tests/unit/`, `tests/integration/`, `tests/performance/`, `docs/`, `tmp/` (each with `__init__.py` or `.gitkeep` as appropriate; `tmp/` must exist but never be committed)
- [X] T002 Initialize `pyproject.toml` (PEP 621): name `schwab-mcp`, requires-python `>=3.11`, dependencies `schwabdev==4.0.0` and `mcp` (official MCP SDK), dev dependencies `pytest` and `pytest-asyncio`; console script `schwab-mcp = "schwab_mcp.cli:main"`; run `uv sync` to create the lockfile and venv
- [X] T003 [P] Configure `.gitignore` (add `tmp/`, `*.env`, `.venv/`, any `tokens.db*`, `auth.lock` patterns — token/credential artifacts must never be committable per FR-003) and pytest configuration in `pyproject.toml` (testpaths `tests`, markers `performance`, strict mode)

**Checkpoint**: `uv run python -c "import schwabdev, mcp"` succeeds; project layout matches plan.md.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented: error taxonomy, config loading, redaction/event logging, token-store peek/advisory lock.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

> All four test tasks below are written FIRST and must FAIL before their implementation tasks run (constitution Principle I).

- [X] T004 [P] Write failing unit tests for the error taxonomy in `tests/unit/test_errors.py`: assert all 7 error types from data-model.md exist (`MissingConfigError`, `InvalidConfigError`, `AuthorizationCancelledError`, `TokenStoreCorruptedError`, `ReauthorizationRequiredError`, `ConcurrentAuthError`, `ConnectivityError`), all subclass a common `AuthError`, each carries its distinct fixed actionable message per the data-model.md mapping table, and each exposes its exit code (2, 2, 3, 5, 4, 6, 7 respectively) — SC-005's distinctness is asserted by comparing messages pairwise
- [X] T005 [P] Write failing unit tests for config loading in `tests/unit/test_config.py`: missing `SCHWAB_APP_KEY`/`SCHWAB_APP_SECRET` → `MissingConfigError` (fail fast, FR-008); empty-after-strip values → `MissingConfigError`; `SCHWAB_CALLBACK_URL` optional with default `https://127.0.0.1`; `SCHWAB_TOKEN_DB` optional with default `~/.schwab-mcp/tokens.db` (FR-012); `SCHWAB_TOKEN_DB` ending with `/` or empty → `InvalidConfigError` before filesystem access; loaded credentials are registered with the redaction filter (FR-006); NO format/length re-validation duplicated in this module (DRY — schwabdev owns it)
- [X] T006 [P] Write failing unit tests for the redaction filter and auth events in `tests/unit/test_log.py`: a logging Filter that scrubs every registered secret value (app key, app secret, access/refresh/id tokens, authorization codes) replacing them with `***` in any record (FR-006); filter must be installable on both the root logger and the `Schwabdev` logger; `auth_event(event, outcome, detail=...)` emits to **stderr** (never stdout — MCP stdio channel) with ISO-8601 UTC timestamp in the exact line format from contracts/events.md; event values restricted to `auth_start|auth_success|auth_failure|renewal_success|renewal_failure` (FR-014)
- [X] T007 [P] Write failing unit tests for the token-store peek and advisory auth lock in `tests/unit/test_tokens.py` (use `tmp/` paths — never real `~/.schwab-mcp`): `peek_store(path)` returns absent-marker for missing file; returns absent-marker (not an exception, not a crash) for corrupted content such as `not a database` (FR-009); returns present-marker when a SQLite file with the schwabdev `schwabdev` table row exists; `enforce_permissions(path)` sets `0o600` on file and `0o700` on its directory (FR-003); `AuthLock(path)` second concurrent non-blocking acquire in the same process raises `ConcurrentAuthError`, and a held lock does not corrupt or modify the token DB (FR-011)
- [X] T008 Implement the error taxonomy in `src/schwab_mcp/errors.py` making T004 pass: `AuthError` base + the 7 subclasses, each with its fixed message and exit code exactly as the data-model.md failure-mode table specifies (depends on T004)
- [X] T009 [P] Implement config loading in `src/schwab_mcp/config.py` making T005 pass: single `load_config()` reading env vars per contracts/configuration.md, failing fast, registering secrets with the redaction filter; no config file parsing, no duplicated schwabdev validation (depends on T005, T008)
- [X] T010 [P] Implement redaction filter and auth event emitter in `src/schwab_mcp/log.py` making T006 pass: one `install_redaction_filter(logger)` plus one `register_secret(value)` plus one `auth_event()` function (single implementation shared by `auth` and `serve` — DRY) (depends on T006, T008)
- [X] T011 Implement token-store peek, permission enforcement, and advisory auth lock in `src/schwab_mcp/tokens.py` making T007 pass: `peek_store()`, `enforce_permissions()`, `AuthLock` using an OS-level non-blocking exclusive advisory lock (`fcntl.flock` on POSIX); the module wraps — never re-implements — schwabdev's token persistence (depends on T007, T008, T010)
- [X] T012 [P] Create `src/schwab_mcp/__init__.py` (package metadata, no logic) and `src/schwab_mcp/__main__.py` delegating `python -m schwab_mcp` to `schwab_mcp.cli.main`

**Checkpoint**: Foundation ready — `uv run pytest tests/unit -q` green (T004–T007 now passing); `uv run python -m schwab_mcp --help` runs (may error on missing subcommands until T014). User story implementation can now begin.

---

## Phase 3: User Story 1 - First-time authorization (Priority: P1) 🎯 MVP

**Goal**: An explicit `schwab-mcp auth` command performs the complete OAuth browser flow (print URL → open browser → owner pastes redirect URL → schwabdev exchanges code) and stores a usable token set locally; an authenticated read then succeeds with no further manual steps.

**Independent Test**: With valid configured credentials, run `schwab-mcp auth`, complete the Schwab login, verify a token store exists at the configured path with `0o600` permissions, the command exits `0`, prints a secret-free success confirmation, and emitted `auth_start`/`auth_success` events; a subsequent authenticated API call succeeds. (Automated: same flow against a stubbed schwabdev client.)

### Tests for User Story 1 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T013 [P] [US1] Write failing integration tests for the authorization flow in `tests/integration/test_auth.py` using a stubbed schwabdev client (no network, no real credentials): empty store → `auth` triggers the `call_on_auth` hook (schwabdev v4 auto-starts auth when the DB is empty; verify with `open_browser_for_auth=False`); hook prints the authorization URL to the owner and calls `webbrowser.open` (stubbed) with a paste-prompt fallback if the browser cannot open (no hang); successful paste → schwabdev exchange → success confirmation on stdout with **zero** secret material (FR-006) → exit `0` → token store exists with `0o600` permissions → `auth_start` and `auth_success` events emitted per contracts/events.md; cancelled/empty paste → exit `3` with the retry message and the existing store untouched (FR-010)

### Implementation for User Story 1

- [X] T014 [US1] Implement `main()` and the `auth` subcommand in `src/schwab_mcp/cli.py` making T013 pass: argparse with subcommands; `auth` sequence per contracts/cli.md — `load_config()` → acquire `AuthLock` (`ConcurrentAuthError` → exit `6`) → emit `auth_start` → instantiate `schwabdev.Client(app_key, app_secret, callback_url, tokens_db=SCHWAB_TOKEN_DB, call_on_auth=<hook>, open_browser_for_auth=False)` where the hook prints the URL, opens the browser via `webbrowser.open` (falling back to URL-only prompt on failure), prompts for the pasted redirect URL, and returns it → `enforce_permissions()` on the store → emit `auth_success` → exit `0`; map all `AuthError` types to their exit codes with the top-level handler (T019 lands the shared handler — until then, minimal local mapping so `auth` alone is testable) (depends on T013, T009, T010, T011, T012)

**Checkpoint**: At this point, User Story 1 is fully functional and independently testable (MVP). `uv run pytest tests/integration/test_auth.py -q` green.

---

## Phase 4: User Story 2 - Silent reuse across sessions (Priority: P2)

**Goal**: On every later start, `schwab-mcp serve` loads stored tokens and establishes authenticated access with no browser interaction, proactively verifying access before signaling ready; expired access credentials renew automatically via the refresh credential.

**Independent Test**: With a stored valid token set, start `serve` twice: no browser/prompt appears, a proactive `linked_accounts()` read succeeds before ready, and startup completes within 5 seconds (SC-004). With a simulated expired access token, the next request triggers silent renewal and succeeds.

### Tests for User Story 2 ⚠️

- [X] T015 [P] [US2] Write failing integration tests for server startup in `tests/integration/test_serve.py` using a stubbed schwabdev client: valid store → client constructed with `tokens_db` from config and a `call_on_auth` hook that raises `ReauthorizationRequiredError` (so no browser/prompt can EVER occur in serve context — FR-001); one proactive `linked_accounts()` read happens BEFORE the MCP stdio transport connects (assert ordering; FR-013, SC-004); absent store → no client constructed at all, exit `4` before any MCP handshake; expired access token with valid refresh → silent automatic renewal (no interactive hook invocation), `renewal_success` event emitted; store with `SCHWAB_TOKEN_DB` custom path honored (FR-012); server registers **zero** MCP tools in this feature (assert the FastMCP server exposes no tools)

### Implementation for User Story 2

- [X] T016 [US2] Implement the startup/validation sequence in `src/schwab_mcp/server.py` making T015 pass: `load_config()` → `peek_store()` (absent → `ReauthorizationRequiredError`; corrupted → `TokenStoreCorruptedError`, store not deleted — FR-009) → construct schwabdev client with the guard hook → proactive `client.linked_accounts()` read (map network failure → `ConnectivityError`) → emit `renewal_success`/`renewal_failure` events on refresh → only then connect the FastMCP stdio transport (`mcp.server.fastmcp.FastMCP`, stdio) with no tools registered (depends on T011, T014)
- [X] T017 [US2] Wire the `serve` subcommand into `src/schwab_mcp/cli.py` with exit-code mapping per contracts/cli.md (2/4/5/7 pre-ready failures), ensuring stdout is reserved exclusively for the MCP protocol channel and all logs go to stderr (depends on T016)

**Checkpoint**: User Stories 1 AND 2 both work independently. `uv run pytest tests/integration/test_serve.py -q` green.

---

## Phase 5: User Story 3 - Recoverable failure states (Priority: P3)

**Goal**: Every authentication failure mode produces a distinct, actionable message and a non-hanging exit: missing config, invalid config, cancelled authorization, expired-beyond-recovery token set, corrupted token store, concurrent authorization, connectivity failure.

**Independent Test**: Force each failure condition (missing/invalid credentials, absent/corrupted/expired token set, second concurrent `auth`, network cut during refresh) and verify each yields its distinct message (SC-005, pairwise-distinct), the documented exit code, no hang (bounded exit), no raw traceback, and no secret material.

### Tests for User Story 3 ⚠️

- [X] T018 [P] [US3] Write failing integration tests for all failure modes in `tests/integration/test_failures.py`, one test per data-model.md mapping row (stubbed client; `tmp/` paths): missing env vars → distinct message + exit `2`; malformed credentials (schwabdev `ValueError`) → distinct message + exit `2`; declined/empty paste → exit `3` + retry message; serve with absent store → exit `4` + "run `schwab-mcp auth`" message; serve with corrupted store (`echo "not a database" > store`) → exit `5`, store left in place (treated as absent — FR-009); second `auth` while first holds the lock → exit `6` immediately (bounded, FR-011); network exception during refresh → exactly ONE retry then distinct connectivity message + exit `7` with stored token set NOT modified or deleted; every case: no traceback in output, no hang (assert bounded runtime), no secrets in any output (depends on T013, T015 for stubs/fixtures — reuse them)

### Implementation for User Story 3

- [X] T019 [US3] Implement the shared top-level error handler in `src/schwab_mcp/cli.py` `main()` making T018's mapping rows pass: single `except AuthError` dispatch printing each error's fixed actionable message to stderr, mapping to its exit code, suppressing all tracebacks (no raw internal errors — FR-007); consolidate T014's temporary local mapping into this single handler (DRY) (depends on T018)
- [X] T020 [US3] Implement connectivity retry-once and store-preservation semantics in `src/schwab_mcp/tokens.py` (exposed via `server.py`/`cli.py` call sites) making T018's connectivity and corruption rows pass: one retry on refresh network failure, then `ConnectivityError`; guarantee the token DB is neither deleted nor rewritten on connectivity failure or when treated-as-absent corruption is detected (depends on T019)

**Checkpoint**: All user stories independently functional. `uv run pytest tests/integration -q` green; every SC-005 failure mode verified one-by-one.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Quality gates and cross-story verification (constitution gates)

- [X] T021 [P] Write and pass the performance test asserting the SC-004 budget in `tests/performance/test_startup_budget.py`: with a valid stubbed store, the full startup-validation sequence (config → peek → client init → proactive read → ready) completes in **< 5 seconds** (assert with generous internal margins for CI, e.g. wall-clock < 5.0 s; the stubbed client must not sleep beyond milliseconds) — registered under the `performance` marker (Principle V performance gate)
- [X] T022 [P] Write and pass the leak sweep in `tests/unit/test_no_secrets_in_output.py`: end-to-end capture of `auth` and `serve` stdout+stderr+all log records under stubbed flows, asserting zero occurrences of the app key, app secret, access token, refresh token, id token, and authorization code (FR-006, SC-003); include the negative control that the redaction filter actually transforms a record containing a secret (Principle V token-usage gate is N/A for this feature — no MCP tool outputs exist; justification recorded in plan.md Complexity Tracking)
- [X] T023 [P] Write owner-facing documentation in `docs/`: `docs/setup.md` (uv install, env file at `~/.schwab-mcp/env` outside the repo per contracts/configuration.md, app-registration prerequisite) and `docs/authentication.md` (auth flow walkthrough, paste-the-redirect-URL explanation, re-auth guidance, failure-mode recovery table referencing data-model.md); documentation content must contain no real credentials and lives only in `docs/` per the constitution layout
- [X] T024 Run the full quickstart.md validation sequence (Scenarios A–C) with the stubbed flows and the automated suite: `uv run pytest -q` fully green with no skipped tests, `tmp/` confirmed git-ignored, and verify every constitution quality gate (test-first, suite, performance, leak check, DRY/KISS review, layout) before completion; record the gate results in the commit description per the constitution's Commit Discipline

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - US1 → US2 → US3 order recommended (US2's `serve` reuses US1's cli skeleton; US3's tests reuse US1/US2 fixtures)
  - US2 and US3 test tasks (T015, T018) can be written in parallel once their predecessor test files exist
- **Polish (Phase 6)**: Depends on all user stories being complete (T024 runs everything)

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) — no dependencies on other stories
- **User Story 2 (P2)**: Depends on US1's `cli.py` skeleton (T014) for the subcommand structure, but its own tests (T015) can be written in parallel with US1 implementation
- **User Story 3 (P3)**: Depends on US1+US2 paths existing to exercise failure modes end-to-end; its error taxonomy is already foundational (T008)

### Within Each User Story

- Tests written FIRST and observed FAILING (constitution Principle I)
- Core implementation before wiring
- Story complete before moving to next priority

### Parallel Opportunities

- T003, T004, T005, T006, T007 (Phase 1–2, different files)
- T009, T010, T012 (different files, after T008)
- T013 and T015 test-authoring can proceed in parallel (different files)
- T021, T022, T023 (Polish, different files)

---

## Parallel Example: Foundational Phase

```bash
# Launch all foundational test-writing tasks together (TDD red phase):
Task: "Write failing unit tests for error taxonomy in tests/unit/test_errors.py"
Task: "Write failing unit tests for config loading in tests/unit/test_config.py"
Task: "Write failing unit tests for redaction/events in tests/unit/test_log.py"
Task: "Write failing unit tests for token-store peek/lock in tests/unit/test_tokens.py"
```

## Parallel Example: Polish Phase

```bash
Task: "Performance test SC-004 in tests/performance/test_startup_budget.py"
Task: "Leak sweep SC-003 in tests/unit/test_no_secrets_in_output.py"
Task: "Documentation in docs/setup.md and docs/authentication.md"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T003)
2. Complete Phase 2: Foundational (T004–T012) — CRITICAL, blocks all stories
3. Complete Phase 3: User Story 1 (T013–T014)
4. **STOP and VALIDATE**: `schwab-mcp auth` works end-to-end (owner run per quickstart.md Scenario A)
5. MVP delivered — the owner can authorize; `serve` comes next

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. Add US1 → test independently → **MVP** (first authorization works)
3. Add US2 → test independently → headless server with silent reuse
4. Add US3 → test independently → all failure modes actionable
5. Polish → performance/leak gates → quickstart validation → done

### Notes

- Tests are MANDATORY in this feature (constitution TDD), not optional
- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Verify tests fail before implementing
- Commit after each task or logical group (green-before-commit + descriptive message per constitution Commit Discipline)
- Stop at any checkpoint to validate a story independently
- Avoid: vague tasks, same-file conflicts (cli.py tasks T014/T017/T019 are sequential by design), cross-story dependencies that break independence

---

## Phase 7: Convergence

**Purpose**: Gaps found by `/speckit.converge` assessing the current code against spec.md, plan.md, and tasks.md (all previously checked tasks verified as complete; 209 tests passing). Tasks below are appended work, test-first per constitution Principle I.

- [X] T025 Add corrupted-token-store handling to the `auth` path per FR-009 (partial): write the failing integration test first in `tests/integration/test_failures.py` (run `auth` with a store containing `not a database` → exit `5` with the `TokenStoreCorruptedError` message, no traceback, store content unmodified), then in `src/schwab_mcp/cli.py` `run_auth` peek the store status (e.g. `peek_store_status`) BEFORE constructing the schwabdev client and raise `TokenStoreCorruptedError` on a corrupted store so the raw `sqlite3.DatabaseError` traceback can never surface
- [X] T026 Rework completion/failure detection in `src/schwab_mcp/cli.py` `run_auth` per FR-007, FR-002, US1/AC1 and contracts/cli.md Behavior 3–5 (contradicts): write failing integration tests first in `tests/integration/test_auth.py` covering (a) empty paste with non-interactive stdin (`sys.stdin.isatty()` False) → exit `3` + `auth_failure` event + retry message, (b) pasted URL that fails the schwabdev exchange → exit `3`, never "Authorization successful"/`auth_success`/exit `0` unless `peek_store` confirms a stored token set, and (c) with an auto-invoking (real-client-like) stub the URL print + paste prompt happen exactly ONCE per attempt (no double prompt, single `webbrowser.open`); then derive success exclusively from `peek_store(config.token_db)` after the flow and restructure the fallback hook invocation so the hook/prompt runs once per attempt regardless of whether the schwabdev client invoked it itself
- [X] T027 Emit `renewal_success`/`renewal_failure` only for actual refresh/validation outcomes in `src/schwab_mcp/server.py` per FR-014 and contracts/events.md (partial): write/adjust the failing assertions in `tests/integration/test_serve.py` first (a connectivity failure during proactive validation must NEVER be preceded by a `renewal_success` line; no `renewal_success` for "access token loaded from store" or "server reaching ready state" transitions), then remove the pre-validation and ready-state `renewal_success` emissions so the event stream cannot contain `renewal_success` followed by `renewal_failure`
- [X] T028 Align the advisory auth lock path with contracts/cli.md Behavior 2 (`~/.schwab-mcp/auth.lock`) instead of `<token_db>.lock` in `src/schwab_mcp/tokens.py` `AuthLock` per plan contract cli.md (partial): update `tests/unit/test_tokens.py` expectations first (locking is global across token-store paths; a second concurrent acquire still raises `ConcurrentAuthError`; the token DB itself is never opened/modified by the lock), then change the lock path derivation accordingly while keeping `fcntl.flock` non-blocking semantics (FR-011)
- [X] T029 Amend FR-006/SC-003 (owner manual validation finding): the displayed authorization URL must contain the client_id (app key) in full — it is public by OAuth design and the URL must be usable as-is (a redacted `client_id=***` forced the owner to hand-edit the URL during the live Scenario A run when the browser session was rejected with error 4001). Test-first: `tests/unit/test_no_secrets_in_output.py` `TestAuthUrlUsability` (printed URL contains real client_id + redirect_uri, no `client_id=***`, browser URL == printed URL) plus updated sweep assertions (app key allowed ONLY inside the authorization URL; app secret/tokens/codes still redacted everywhere; never logged), `tests/integration/test_auth.py` leak test updated to the same rule; then `src/schwab_mcp/cli.py` `auth_hook` prints the URL unredacted (`_redact` removed as unused). Docs amended: spec.md FR-006/SC-003, data-model.md `auth_url` row, contracts/cli.md output guarantees, quickstart.md Scenario A (add "Session rejected" 4001 → incognito-window guidance)
- [X] T031 Restructure owner-facing docs in Spanish with operational lessons from the live validation: replace `docs/setup.md` + `docs/authentication.md` with `docs/installation.md` (requirements, `uv sync`, portal app checklist — `Ready for Use` status, both APIs, slash-free callback URL per schwabdev's validation, key+secret from the same app, env file outside the repo, per-terminal sourcing rule with `echo` verification) and `docs/uso.md` (paste-the-redirect-URL walkthrough, one-run rule — the browser URL and the paste terminal must belong to the same `auth` run, `Session rejected` 4001 → incognito guidance, `serve` behavior + MCP client connection example with `env` block, token lifecycle, failure-mode exit table, troubleshooting matrix covering the errors observed during live validation: trailing-slash ValueError, `invalid_grant` RedirectURI mismatch, stale shell variables, mixed key/secret). No real credentials in docs content (FR-006)
