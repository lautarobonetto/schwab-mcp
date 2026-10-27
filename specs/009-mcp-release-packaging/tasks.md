---

description: "Task list for feature 009-mcp-release-packaging"
---

# Tasks: MCP Release Packaging

**Input**: Design documents from `/specs/009-mcp-release-packaging/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/build-command.md, contracts/archive-layout.md, contracts/manuals-set.md, quickstart.md

**Tests**: INCLUDED — the project constitution mandates TDD (tests written first, must FAIL, then minimal implementation). Every story phase starts with its test tasks.

**Organization**: Tasks grouped by user story (US1 = build command P1, US2 = recipient experience P2, US3 = clean-package scans P3).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- All paths are repository-root relative (single project layout per plan.md)

## Path Conventions

- Packaging tooling: `src/schwab_mcp_release/` (maintainer-only, excluded from shipped wheel)
- Runtime package (shipped): `src/schwab_mcp/`
- Tests: `tests/unit/`
- Recipient manuals: `docs/release/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Scaffolding so the maintainer-only tooling exists and the shipped wheel is structurally clean.

- [X] T001 Create maintainer-only package skeleton with module docstrings referencing `specs/009-mcp-release-packaging/contracts/`: `src/schwab_mcp_release/__init__.py`, `src/schwab_mcp_release/__main__.py`, `src/schwab_mcp_release/cli.py`, `src/schwab_mcp_release/wheel.py`, `src/schwab_mcp_release/archive.py`, `src/schwab_mcp_release/manifest.py`, `src/schwab_mcp_release/checks.py` (empty/stub functions only, no logic)
- [X] T002 In `pyproject.toml`: register maintainer-only console script `[project.scripts] schwab-mcp-release = "schwab_mcp_release.cli:main"` AND replace `[tool.setuptools.packages.find]` with an explicit packages list `packages = ["schwab_mcp"]` so `schwab_mcp_release` is structurally excluded from the shipped wheel (FR-003; research D2/D3)
- [X] T003 [P] Add `dist/` to `.gitignore` (build output per plan.md Complexity Tracking)
- [X] T004 Verify `uv sync && uv run schwab-mcp-release --help` resolves the skeleton (argparse stub printing usage, exit 0) and confirm `uv build` output does NOT contain `schwab_mcp_release` (spot-check wheel contents manually into `tmp/`)

**Checkpoint**: Tooling package importable as `schwab-mcp-release` command; shipped wheel structurally clean.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Single sources of truth (version, allowlist) and the archive content artifacts (manuals, install script). BLOCKS all user stories: the completeness check (US1) requires every allowlist member to exist, so manuals and install.sh must exist before any build can succeed.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Tests first (foundational)

- [X] T005 [P] Write failing test `tests/unit/test_release_version.py`: version resolution returns exactly the `project.version` string from `pyproject.toml` (single source of truth, FR-005, research D4); fails if the file is missing or malformed
- [X] T006 [P] Write failing test `tests/unit/test_release_allowlist.py`: allowlist module exposes the exact member set from `contracts/archive-layout.md` — every path under the wrapping top-level directory `schwab-mcp-<version>/`: archive-root `README.md` (verbatim copy of `docs/release/README.md`), wheel path pattern, 4 manuals under `manuals/` (installation, first-run-authentication, usage, troubleshooting), `install.sh`, `manifest.json`, `SHA256SUMS` — with required-flag per member and forbidden-content patterns (dev-material + secret path rules)

### Implementation (foundational)

- [X] T007 [P] Implement version resolution in `src/schwab_mcp_release/version.py` to pass T005 (read `pyproject.toml` `project.version`; explicit error naming the file if unreadable)
- [X] T008 [P] Implement the archive allowlist as the single source of truth in `src/schwab_mcp_release/allowlist.py` to pass T006 (used by BOTH archive assembly and completeness check — DRY per plan.md; quote rules verbatim from `contracts/archive-layout.md`: forbidden paths `tests/`, `specs/`, `plans/`, `.git*`, `__pycache__/`, `*.egg-info/`; forbidden names `.env`, `*.pem`, `*token*db*`, `*secret*`, `*credential*`)
- [X] T009 [P] Author recipient manuals in English (FR-006, FR-007, contracts/manuals-set.md): `docs/release/README.md` (overview, version visibility, integrity verification steps), `docs/release/installation.md` (prerequisite Python >= 3.11 with check command, install steps with expected outcomes, prerequisite-failure resolutions, in-place upgrade preserving `~/.schwab-mcp/tokens.db` per FR-015), `docs/release/first-run-authentication.md` (own Schwab app credentials, `schwab-mcp auth` steps, credential-safety storage rules FR-014, failure symptoms), `docs/release/usage.md` (connect AI client over stdio, available tools, automatic token renewal behavior FR-013, configuration), `docs/release/troubleshooting.md` (symptom→resolution table: missing prerequisite, auth failure, AI-client connection failure, upgrade problems; `schwab-mcp auth-status` diagnostics; what to report and what NEVER to share)
- [X] T010 [P] Author `install.sh` (archive root, per research D11): checks `python3` >= 3.11 (actionable error pointing to the matching section of `manuals/installation.md`), creates venv `.venv`, installs the bundled wheel, verifies `schwab-mcp --help` succeeds; every failure prints an actionable message (FR-012); upgrade-safe (re-running replaces the install in place, never touches `~/.schwab-mcp/`)

**Checkpoint**: Foundation ready — version + allowlist sources of truth exist; all archive content artifacts authored. User stories can begin.

---

## Phase 3: User Story 1 — Maintainer builds a distribution package with one command (Priority: P1) 🎯 MVP

**Goal**: `uv run schwab-mcp-release build` produces `dist/schwab-mcp-<version>.zip` + `.sha256`, complete per allowlist, reproducible, with dirty-tree guard and contract-conformant stdout/exit codes (contracts/build-command.md).

**Independent Test**: Run the build command in a clean checkout; inspect the archive for completeness (wheel with only `schwab_mcp`, 5 manuals, install.sh, manifest, SHA256SUMS) and correct stdout/exit codes. Delivers a distributable package with no other story implemented.

### Tests for User Story 1 (write FIRST, ensure they FAIL)

- [ ] T011 [P] [US1] Write failing test `tests/unit/test_release_wheel.py`: wheel build invokes the existing toolchain via `uv build --wheel` (research D2 — reuse, no re-implementation) and the produced wheel contains ONLY the `schwab_mcp` package (no `schwab_mcp_release`, no tests, no docs) — wheel contents verified by opening the wheel zip in the test
- [ ] T012 [P] [US1] Write failing test `tests/unit/test_release_archive.py`: archive assembly emits exactly the allowlist member set, all wrapped under the single top-level directory `schwab-mcp-<version>/` (FR-002, F1), member timestamps normalized and fixed member order, and two consecutive assemblies produce byte-equivalent archives (FR-011, research D1/D4)
- [ ] T013 [P] [US1] Write failing test `tests/unit/test_release_manifest.py`: `manifest.json` fields per data-model.md (`version`, `build_dirty`, `members[]` each with path/size/sha256); `SHA256SUMS` has one sorted line per member; outer `schwab-mcp-<version>.zip.sha256` contains `<sha256>  schwab-mcp-<version>.zip` (FR-010)
- [ ] T014 [P] [US1] Write failing test `tests/unit/test_release_checks.py`: completeness check passes when every required allowlist member is present in the archive and FAILS naming the missing member exactly like `MISSING: manuals/installation.md` (FR-008); a zero-byte required member counts as missing
- [ ] T015 [P] [US1] Write failing test `tests/unit/test_release_cli.py`: CLI stdout matches the stable contract lines (`BUILD`, `WHEEL`, `ARCHIVE`, `CHECKS completeness=PASS` — US1 scope; the `exclusion`/`secrets` fields are appended by T032 in US3, `OUT`, `OK build complete in <s>s`) and exit codes: 0 success (also with `--allow-dirty`, recording `build_dirty: true`), 1 validation failure naming missing piece, 2 dirty tree without override with message `working tree has uncommitted changes; pass --allow-dirty to build anyway`, 3 wheel-build prerequisite failure (FR-005, research D4)
- [ ] T016 [P] [US1] Write failing performance test `tests/unit/test_release_build_performance.py` marked `@pytest.mark.performance`: full build completes in < 60 s (SC-002)

### Implementation for User Story 1

- [ ] T017 [US1] Implement wheel build in `src/schwab_mcp_release/wheel.py` to pass T011 (invoke `uv build --wheel` — reuse the existing toolchain; locate produced wheel; verify shipped contents are only `schwab_mcp`)
- [ ] T018 [US1] Implement manifest + checksums in `src/schwab_mcp_release/manifest.py` to pass T013 (stdlib `hashlib`; member inventory single pass reused for SHA256SUMS)
- [ ] T019 [US1] Implement archive assembly in `src/schwab_mcp_release/archive.py` to pass T012 (stdlib `zipfile`; members from allowlist T008; normalized timestamps; fixed order)
- [ ] T020 [US1] Implement completeness check in `src/schwab_mcp_release/checks.py` to pass T014 (driven by the same allowlist — no duplicated member list)
- [ ] T021 [US1] Implement CLI orchestration in `src/schwab_mcp_release/cli.py` to pass T015: build flow wheel → archive → manifest → completeness; exit codes 0/1/2/3; `--allow-dirty` and `--output-dir` flags; stable stdout; build staging under `tmp/release-staging/` cleaned up on any failure; on failure NO checksum file written and no archive presented as success (FR-008)

**Checkpoint**: User Story 1 fully functional and independently testable: one command emits a complete, reproducible, versioned package with checksum. Validate via quickstart.md Scenarios 1, 4, 5.

---

## Phase 4: User Story 2 — Recipient installs and runs the MCP from the package (Priority: P2)

**Goal**: A recipient with only the archive + manuals can install, authenticate, connect an AI client, and invoke tools; version is visible post-install; upgrades preserve credentials.

**Independent Test**: From the US1 archive only, follow `manuals/` end to end on a clean machine (quickstart.md Scenario 6): verify checksum → install.sh → `schwab-mcp auth` → `schwab-mcp serve` → one successful read-only tool call.

### Tests for User Story 2 (write FIRST, ensure they FAIL)

- [ ] T022 [P] [US2] Write failing test `tests/unit/test_cli_version.py` (regression check first: document current `schwab-mcp --help` behavior): version string is visible in `schwab-mcp --help` output and equals `pyproject.toml` version (FR-005 recipient visibility)
- [ ] T023 [P] [US2] Write failing test `tests/unit/test_install_script.py`: run `install.sh` in a sandbox under `tmp/` with an overridden `HOME` — missing-prerequisite path prints the actionable message matching `manuals/installation.md` wording; success path creates venv, installs wheel, `schwab-mcp --help` works; re-run (upgrade) replaces install and the overridden-`HOME` sandbox proves nothing was written under `~/.schwab-mcp/` (FR-015, FR-012)

### Implementation for User Story 2

- [ ] T024 [US2] Implement version visibility in `src/schwab_mcp/cli.py` to pass T022 (print version in help output; version sourced from package metadata — no new duplicate constant, DRY)
- [ ] T025 [US2] Align `install.sh` failure messages with `docs/release/installation.md` sections to pass T023 (each error names the resolution section; FR-012)
- [ ] T026 [P] [US2] Audit manual coverage against `contracts/manuals-set.md` acceptance mapping (FR-006…FR-015, SC-001, SC-005): fill any gaps found in `docs/release/README.md`, `docs/release/installation.md`, `docs/release/first-run-authentication.md`, `docs/release/usage.md`, `docs/release/troubleshooting.md` (e.g., integrity verification command, upgrade section, report-vs-never-share guidance)
- [ ] T027 [US2] Execute recipient-journey validation per `specs/009-mcp-release-packaging/quickstart.md` Scenarios 1, 2, 6 (install from package only, guided time ≤ 15 min target SC-001) and record outcomes; fix any manual or script gap discovered, re-running the scenario after each fix

**Checkpoint**: User Stories 1 AND 2 work independently: package builds AND a recipient can complete install → auth → serve → tool call using only the package contents.

---

## Phase 5: User Story 3 — The package is free of development material and secrets (Priority: P3)

**Goal**: Build fails (exit 1, member named, content never printed) if any dev-material or secret-bearing member is detected in the final archive (FR-003, FR-004, FR-009).

**Independent Test**: Introduce a dev-material file or a secret-bearing file among archive inputs → build fails naming the member; clean build passes with `secrets=PASS exclusion=PASS` in stdout.

### Tests for User Story 3 (write FIRST, ensure they FAIL)

- [ ] T028 [P] [US3] Write failing test `tests/unit/test_release_checks_dev_material.py`: scan over final archive members detects forbidden content (paths `tests/`, `specs/`, `plans/`, `__pycache__/`, `.git*`, `*.egg-info/`, editable source trees, dev config) and fails naming the offending member (FR-003, FR-009)
- [ ] T029 [P] [US3] Write failing test `tests/unit/test_release_checks_secrets.py`: scan detects secret-bearing members (`.env`, `*.pem`, `*token*db*`, `*secret*`, `*credential*` names; credential-shaped content patterns in text members) and fails naming the member ONLY — asserts matched content never appears in the failure output (FR-004, credential safety)

### Implementation for User Story 3

- [ ] T030 [US3] Implement dev-material exclusion scan in `src/schwab_mcp_release/checks.py` to pass T028 (rules from the allowlist module T008 — single source of truth for forbidden patterns)
- [ ] T031 [US3] Implement secret scan in `src/schwab_mcp_release/checks.py` to pass T029 (stdlib-only pattern scan per research D6; report member name only)
- [ ] T032 [US3] Wire both scans into the build flow in `src/schwab_mcp_release/cli.py` before success: stdout `CHECKS completeness=PASS exclusion=PASS secrets=PASS` line updated accordingly; any scan failure → exit 1, offending member named, no checksum file written (FR-009); extend `tests/unit/test_release_cli.py` with the failing-scan exit-code cases

**Checkpoint**: All three user stories independently functional: build is complete (US1), usable by a recipient (US2), and provably clean (US3). Validate via quickstart.md Scenario 3.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation currency, full validation, and governance gates.

- [ ] T033 [P] Update documentation for the new capability: `docs/CHANGELOG.md` entry, maintainer release instructions (how to run `schwab-mcp-release build` and distribute) in `docs/uso.md` or a new `docs/release-mantenimiento.md`, and `README.md` pointer — documentation affected by the change MUST be in the same commit (commit discipline)
- [ ] T034 Run the complete `specs/009-mcp-release-packaging/quickstart.md` validation (Scenarios 1–8) end to end and record results
- [ ] T035 Run full suite `uv run pytest` — green, 0 skipped (commit gate); refresh the codebase-memory-mcp index for this repository (graph currency gate, constitution Principle VI); verify token-usage gate N/A justification stands (no tool outputs changed)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately
- **Foundational (Phase 2)**: depends on Phase 1 (skeleton + script registration); BLOCKS all user stories (US1's completeness check requires the allowlist, manuals, install.sh)
- **US1 (Phase 3)**: depends on Phase 2
- **US2 (Phase 4)**: depends on US1 (needs a built archive to validate the recipient journey)
- **US3 (Phase 5)**: depends on US1 (scans integrate into the US1 build flow) — can run in parallel with US2 if staffed
- **Polish (Phase 6)**: depends on US1 + US2 + US3

### User Story Dependencies

- **US1 (P1)**: first; no dependencies on other stories
- **US2 (P2)**: consumes US1's archive; independently testable once US1 exists
- **US3 (P3)**: extends US1's checks; independently testable once US1 exists

### Within Each User Story

- Tests FIRST and failing before implementation (constitution Principle I)
- Foundational sources of truth (T005–T008) before assembly/checks
- Implementation in data-flow order: wheel → manifest → archive → checks → CLI

### Parallel Opportunities

- Phase 1: T003 alone
- Phase 2: T005+T006 (tests) in parallel, then T007+T008+T009+T010 in parallel
- Phase 3: T011–T016 (all six test files) in parallel; implementation T017–T020 partly parallel (wheel/manifest/archive independent), T021 last
- Phase 4: T022+T023 tests in parallel; T024/T025 then T026; T027 sequential (validation)
- Phase 5: T028+T029 tests in parallel; T030/T031 parallel; T032 last
- US2 and US3 can proceed in parallel after US1 (different files: US2 touches `docs/release/` + `src/schwab_mcp/cli.py` + `install.sh`; US3 touches `src/schwab_mcp_release/checks.py` + `cli.py` wiring — coordinate T032/T021 same file)

---

## Parallel Example: User Story 1

```bash
# Launch all US1 tests together (they must all fail first):
Task: "tests/unit/test_release_wheel.py"
Task: "tests/unit/test_release_archive.py"
Task: "tests/unit/test_release_manifest.py"
Task: "tests/unit/test_release_checks.py"
Task: "tests/unit/test_release_cli.py"
Task: "tests/unit/test_release_build_performance.py"

# Then implementation, wheel/manifest/archive in parallel:
Task: "src/schwab_mcp_release/wheel.py"
Task: "src/schwab_mcp_release/manifest.py"
Task: "src/schwab_mcp_release/archive.py"
# Then checks, then CLI orchestration:
Task: "src/schwab_mcp_release/checks.py"
Task: "src/schwab_mcp_release/cli.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup) + Phase 2 (Foundational)
2. Complete Phase 3 (US1): one command → complete reproducible package
3. **STOP and VALIDATE**: quickstart.md Scenarios 1, 4, 5
4. Deliverable exists (maintainer can hold a distributable archive), though recipient journey is not yet validated

### Incremental Delivery

1. Setup + Foundational → sources of truth and content artifacts ready
2. US1 → MVP: build command works (validate independently)
3. US2 → recipient journey proven from the package only
4. US3 → clean-package guarantee enforced by the build itself
5. Polish → docs currency, quickstart full pass, commit gates

### Notes

- Commit after each task or logical group; commit message enumerates changes; docs updated in same commit
- `tmp/` for all scratch (test sandboxes, wheel spot-checks); `dist/` only for build output (git-ignored)
- Never print offending file CONTENT in scan failures — member names only (credential safety)
- Verify tests fail before implementing (TDD gate)