# Research: MCP Release Packaging

**Feature**: 009-mcp-release-packaging | **Date**: 2026-10-26

All unknowns from Technical Context were resolved during planning; the clarifications session (2026-10-26) already fixed package form (archive + documented prerequisites), upgrade path (in-place replace), and manual language (English). This document records the remaining design decisions.

## D1: Distribution artifact format

**Decision**: A single `.zip` archive (`schwab-mcp-<version>.zip`) containing the runtime wheel, manuals, manifest, checksums, and an install script.

**Rationale**: Zip is natively openable on macOS (double-click), fully handled by stdlib `zipfile`, and does not need POSIX exec-bit preservation (no executables ship raw — the entry point comes from the installed wheel's console script). Deterministic output is achievable by normalizing member timestamps and using a fixed member order.

**Alternatives considered**:
- `.tar.gz`: equivalent for this content, but less friendly to non-technical recipients on macOS; no advantage since no exec bits are needed.
- Self-contained virtualenv bundle: not portable across machine paths; violates the clarified decision (recipients install documented prerequisites themselves).
- Platform installer (pkg): heavier tooling, unjustified for 1–5 recipients (KISS).

## D2: What the archive ships as the "runnable server"

**Decision**: A standard built wheel (`schwab_mcp-<version>-py3-none-any.whl`) built from the existing setuptools backend with an **explicit package list** (`packages = ["schwab_mcp"]`), so only the runtime package is included; `schwab_mcp_release` (maintainer tooling) is structurally excluded. Recipient installs the wheel into a Python ≥ 3.11 venv via the included install script.

**Rationale**: Reuses the existing build toolchain (Reuse Before Creation, DRY — version from `pyproject.toml` is the single source of truth). A wheel is the standard, non-editable-in-place distribution form: it carries runtime modules only — no tests, specs, plans, git history, or dev configs — satisfying FR-003 ("not facilitating continuation") without exotic techniques.

**Alternatives considered**:
- Shipping an editable source tree: directly violates FR-003.
- Bytecode-only distribution (`.pyc`): non-standard, fragile across Python versions, breaks console-script generation; rejected (KISS + reliability).
- Obfuscation/anti-reverse-engineering: explicitly out of scope in the spec.

## D3: Build command shape and location

**Decision**: New console script `schwab-mcp-release` (module `src/schwab_mcp_release/`, invoked as `uv run schwab-mcp-release build`), maintainer-only, excluded from the shipped wheel (see D2).

**Rationale**: The recipient-facing CLI (`schwab-mcp`) must stay clean of maintainer tooling; a separate top-level package keeps both command surfaces unambiguous. Python API inside the module stays importable for tests (TDD-friendly), mirroring how `schwab_mcp.cli` is structured and tested.

**Alternatives considered**:
- Shell script at repo root: violates the layout gate (source must live in `src/`) and is harder to unit test.
- Subcommand inside `schwab-mcp` CLI: ships build tooling to recipients (violates FR-003).

## D4: Version stamping and reproducibility

**Decision**: Version is read from `pyproject.toml` (`0.5.1` today) — never re-derived. The build refuses to run on a dirty working tree unless `--allow-dirty` is passed (the produced archive then records the dirty marker in its manifest). Archive member timestamps are normalized to a fixed value; members are written in a deterministic order.

**Rationale**: FR-005 (identifiable version), FR-011 (reproducibility), and the spec edge case about unidentifiable builds are all satisfied by one mechanism. Dirty-tree refusal prevents shipping an untraceable artifact; the explicit override keeps the escape hatch auditable.

**Alternatives considered**:
- Version from git tag: adds a coupling to release workflow not requested; pyproject is already the declared source of truth.

## D5: Completeness and exclusion enforcement

**Decision**: One authoritative **allowlist** (manifest spec in `contracts/archive-layout.md`) drives both archive assembly (FR-002) and the completeness check (FR-008): the check verifies every required member exists in the produced archive and fails naming the missing piece. Exclusion (FR-003) and secret scanning (FR-004) run over the final archive members before success, failing with the offending member name (never printing content).

**Rationale**: A single list is the DRY source of truth for "what must be inside" and "nothing else is added by accident". Scanning the final archive (not the staging tree) catches assembly bugs too.

**Alternatives considered**:
- Denylist (blocklist of dev patterns) as the only guard: weaker — new dev files would ship by default. Allowlist + denylist scan for defense in depth: the denylist scan still runs over members to catch accidental inclusion inside the wheel, but the allowlist governs top-level archive content.

## D6: Secret scanning approach

**Decision**: Stdlib-only scan over archive members: (1) reject any `.env`, key/credential-named files anywhere in the archive; (2) reject text members whose content matches credential patterns (Schwab OAuth tokens/keys shapes, generic `api_key`/`secret` assignment patterns); report the member name only.

**Rationale**: FR-004/FR-009 require the build to fail naming the offending item. The existing test suite already embodies no-secrets-in-output expectations (`tests/unit/test_no_secrets_in_output.py`); patterns are kept simple and the runtime server's own credential-safety behavior is untouched and re-documented in the manuals (FR-013/FR-014).

**Alternatives considered**:
- Third-party secret scanners: new dependency for a tiny surface — rejected (KISS, reuse-before-creation: stdlib suffices at this scale).

## D7: Recipient manuals — set, language, and home

**Decision**: English manuals authored in `docs/release/` (README, installation, first-run-authentication, usage, troubleshooting). `README.md` ships verbatim at the archive ROOT; the other four ship under `manuals/`. Coverage matrix vs FR-006 lives in `contracts/manuals-set.md`.

**Rationale**: `docs/` is the constitutionally mandated home for documentation; copying into the archive satisfies FR-002 (manuals inside the package). English was decided in the clarify session (Q3). Manuals target a technical-but-non-developer recipient (FR-007) and document prerequisites (Python ≥ 3.11), first-run `schwab-mcp auth`, connecting an AI client over stdio, automatic renewal behavior, and in-place upgrade preserving `~/.schwab-mcp/tokens.db` (FR-015).

**Alternatives considered**:
- Writing manuals only in the repo docs and linking: violates FR-002 (manuals must be inside the package; recipient has no repo access).
- Bilingual manuals: rejected in clarify session (English only).

## D8: Integrity verification for recipients

**Decision**: The build emits `dist/schwab-mcp-<version>.zip` plus `dist/schwab-mcp-<version>.zip.sha256` (SHA-256 of the archive). The installation manual's first step is verifying this checksum; the archive's own `SHA256SUMS` covers inner members.

**Rationale**: FR-010 with zero new concepts — one outer checksum for transit integrity, one inner manifest for content completeness. Both verified with standard shell tools documented in the manual.

**Alternatives considered**: GPG signing (key management burden unjustified for a private, 1–5 recipient distribution; out of scope per spec).

## D9: Build output location

**Decision**: `dist/` at the repository root, git-ignored; justified against the fixed layout in `plan.md` (Complexity Tracking) as standard build output.

**Rationale**: PEP-conventional, regenerable, never committed; avoids abusing `tmp/` (whose contents must never be released) for the distribution deliverable.

## D10: Performance & token budgets for this feature

**Decision**: One `@pytest.mark.performance` test asserting a full build completes under 60 s (SC-002). Token-usage gate: N/A — this feature adds no MCP tools and alters no tool outputs; justification recorded in plan.md per constitution Principle V.

**Rationale**: Measurable, automatable, directly tied to a spec success criterion; no token surface is created.

## D11: Prerequisite verification on recipient machines

**Decision**: The included install script checks (a) Python ≥ 3.11 availability (`python3 --version`), (b) creates a venv, (c) installs the wheel, (d) verifies `schwab-mcp --help` runs; each failure prints an actionable message pointing at the matching manual section (FR-012).

**Rationale**: Maps the spec edge case ("machine does not meet a documented prerequisite") to a deterministic, testable behavior without an installer framework (KISS).

**Alternatives considered**: A Python-based installer inside the wheel (can't run before Python exists — chicken-and-egg); platform installer framework (rejected in D1).