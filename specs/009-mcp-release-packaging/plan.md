# Implementation Plan: MCP Release Packaging

**Branch**: `009-mcp-release-packaging` | **Date**: 2026-10-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/009-mcp-release-packaging/spec.md`

## Summary

Add a maintainer-facing build command that produces a distributable archive of the MCP server: the runtime wheel, English recipient manuals, a manifest, and integrity checksums — with built-in completeness, dev-material-exclusion, and secret scans that fail the build explicitly. Recipients install from the archive using the included manuals on a machine that meets documented prerequisites (Python ≥ 3.11); upgrades replace the installation in place, preserving locally stored credentials. No development material (tests, specs, plans, dev configs, editable source tree) ships in the archive.

## Technical Context

**Language/Version**: Python 3.11 (matches existing `requires-python = ">=3.11"`)

**Primary Dependencies**: setuptools (existing build backend), uv (env/build runner — already in use), Python stdlib (`zipfile`, `hashlib`, `tarfile` not needed). No new third-party runtime dependencies.

**Storage**: N/A for this feature — recipient credentials remain in the existing local token DB (`~/.schwab-mcp/tokens.db`, unchanged). Build output is a git-ignored `dist/` directory (standard packaging convention).

**Testing**: pytest (existing suite; unit tests under `tests/unit/`)

**Target Platform**: macOS (development OS family, per spec assumption); recipient needs Python ≥ 3.11 (documented prerequisite)

**Project Type**: CLI (stdio MCP server) + maintainer-only packaging tooling

**Performance Goals**: full build completes in < 60 s (SC-002); archive assembles and scans are part of that budget

**Constraints**:
- Package MUST exclude all dev-only material (FR-003) and secrets (FR-004) — enforced by build-time scans (FR-009)
- Completeness check before build success (FR-008); reproducible output (FR-011)
- Credential safety: nothing secret ever enters the archive or logs
- Fixed repository layout (src/tests/docs/tmp); `dist/` is git-ignored build output

**Scale/Scope**: single maintainer, small number of recipients (1–5); archive size on the order of a few hundred KB

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Notes |
|------|--------|-------|
| I. Test-first (TDD) | PASS | Packaging tooling tests written first (Red → Green): completeness, exclusion, secret scan, version stamping, reproducibility. Regression test not applicable (new feature). |
| II. DRY | PASS | Version is read from `pyproject.toml` (single source of truth). Reuse stdlib `zipfile`/`hashlib`; no duplicate checksum logic. Manual content adapts existing docs knowledge without duplicating behavior descriptions (recipient manuals are new artifacts, not copies). |
| III. Reuse before creation | PASS | Build reuses setuptools/uv (existing toolchain) and stdlib. No new dependency justified needed. Secret-scan reuses the spirit of `tests/unit/test_no_secrets_in_output.py` patterns (documented in research.md). |
| IV. KISS | PASS | Single command, stdlib-only assembly, flat module `src/schwab_mcp_release/`. No installer framework, no update server, no obfuscation. |
| V. Performance & token budgets | PASS | Performance test: build < 60 s (SC-002). Token-usage gate: **N/A — justified**: this feature adds no MCP tool and produces no tool outputs; token consumption of the running server is unchanged. Justification recorded here per constitution. |
| VI. Graph-first discovery | PASS | Design used codebase knowledge graph + targeted reads of `cli.py`/`config.py` to confirm CLI surface and token DB path. |
| Repository layout | PASS | Packaging source in `src/schwab_mcp_release/` (source → `src/`), tests in `tests/`, recipient manuals in `docs/release/` (documentation → `docs/`), scratch in `tmp/`. `dist/` is standard build output (tooling convention, git-ignored) — see Complexity Tracking. |
| Credential safety | PASS | Build scans fail on any secret material found in archive members; nothing is logged verbatim (names only). |
| Commit discipline | PASS (process) | Docs affected (README/CHANGELOG/docs) updated in same commit at implement time. |

## Project Structure

### Documentation (this feature)

```text
specs/009-mcp-release-packaging/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── build-command.md
│   ├── archive-layout.md
│   └── manuals-set.md
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/
├── schwab_mcp/              # Existing runtime package — the ONLY package shipped in the wheel
│   ├── cli.py               #   auth / renew / auth-status / serve (unchanged)
│   ├── config.py            #   token DB path, env config (unchanged)
│   └── ...                  #   server, tokens, renewal, tools (unchanged)
└── schwab_mcp_release/      # NEW maintainer-only packaging tooling (EXCLUDED from shipped wheel)
    ├── __init__.py
    ├── __main__.py          # python -m schwab_mcp_release
    ├── cli.py               # build command: orchestrate build → validate → emit
    ├── wheel.py             # invoke uv/setuptools wheel build
    ├── archive.py           # assemble archive from allowlist + manuals + manifest
    ├── manifest.py          # manifest + SHA256SUMS generation
    ├── version.py           # version resolution from pyproject.toml (single source of truth)
    ├── allowlist.py         # archive member allowlist + forbidden patterns (single source of truth)
    └── checks.py            # completeness / dev-material exclusion / secret scan

tests/
└── unit/
    ├── test_release_cli.py          # build command contract, failure modes
    ├── test_release_archive.py      # allowlist assembly, reproducibility
    ├── test_release_checks.py       # completeness, exclusion, secret scans
    └── test_release_manifest.py     # manifest + checksums, version stamping

docs/
└── release/                 # NEW recipient-facing manuals (English), copied into every archive
    ├── README.md            # package overview + integrity verification pointer
    ├── installation.md      # prerequisites, install, upgrade (FR-006, FR-012, FR-015)
    ├── first-run-authentication.md
    ├── usage.md             # connect AI client, daily use, token renewal behavior
    └── troubleshooting.md

dist/                        # build output (git-ignored) — NOT in any fixed-layout directory
└── schwab-mcp-<version>.zip
```

**Structure Decision**: Two top-level packages under `src/`: the existing runtime package `schwab_mcp` (the only one listed in setuptools `packages`, hence the only one in the shipped wheel) and the new maintainer-only `schwab_mcp_release` (excluded from the wheel by explicit package listing). Recipient manuals live in `docs/release/` and are copied verbatim into each archive, satisfying the layout gate (docs → `docs/`) while FR-002 requires them inside the package.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| `dist/` directory outside the fixed layout (src/tests/docs/tmp) | Standard, expected location for build artifacts (PEP convention); the archive is a distributable deliverable, not scratch. **Ratified**: constitution v1.4.1 (2026-10-26 amendment) adds an explicit build-output exemption for git-ignored, regenerable build-output directories such as `dist/` | `tmp/` rejected: constitution forbids anything in `tmp/` from ever being released/distributed, and the archive is exactly the artifact meant for distribution; root-level custom dir rejected as non-conventional. `dist/` is git-ignored and holds only regenerable build output. |
| Second top-level package `schwab_mcp_release` | The build tooling must live in `src/` (layout gate) but MUST NOT ship inside the distributed wheel (FR-003) | Single package with the release module inside `schwab_mcp` rejected: it would put maintainer build tooling into every recipient installation, directly conflicting with FR-003; explicit setuptools package listing cleanly separates shipped vs. maintainer-only code with zero runtime cost. |

## Post-Design Constitution Re-Check (Phase 1)

- TDD: task order will put packaging-check tests before `checks.py` implementation (enforced in `/speckit.tasks`).
- DRY/KISS: allowlist-driven archive (one authoritative member list) is the single source of truth for both assembly (FR-002) and completeness check (FR-008) — no duplicated list.
- Performance gate: SC-002 (< 60 s) becomes a `@pytest.mark.performance` test.
- Token-usage gate: N/A justified above (no tool outputs produced).
- Layout gate: all new files in `src/`, `tests/`, `docs/`; `dist/` justified above; git-ignores updated at implement time.
- No unresolved NEEDS CLARIFICATION items remain (all resolved in research.md / prior clarify session).