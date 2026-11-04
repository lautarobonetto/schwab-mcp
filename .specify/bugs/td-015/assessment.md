# Bug Assessment: Release: duplicated validation and except-clones in `cmd_build` (DRY)

- **Slug**: td-015
- **Created**: 2026-11-04
- **Source**: pasted text (verbatim copy of the TD-015 entry in `docs/tech-debt.md:551`)
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

Pasted report (also on record at `docs/tech-debt.md`, ledger table line 31 and detail section line 551, status **Open**):

> **TD-015 — Release: duplicated validation and except-clones in `cmd_build` (DRY)**
> Area: `src/schwab_mcp_release/cli.py:74-106`, `archive.py:56-58`, `checks.py`, `wheel.py`
> - `cli.py:92-95` duplicates the source-file validation already performed by `assemble_archive` (`archive.py:56-58`), with divergent message style.
> - Three identical `try/except → print error → return 3` blocks (`74-78, 85-89, 97-106`) collapse into one because `VersionError` and `WheelBuildError` already subclass `ReleaseError` (`version.py:18`, `wheel.py:27`).
> - `wheel.py:45` re-resolves the version by re-reading `pyproject.toml` although `cmd_build` already resolved it (`cli.py:75`) — change signature to `build_wheel(project_root, version, out_dir)`.
> - `checks.py:38` vs `67`: same `wrap/` prefix-strip logic copied; extract `_relative_name(entry, wrap)`.
> Refactor: single `except ReleaseError` around resolve/build/assemble; delete the duplicate validation loop; pass the resolved version through; share the strip helper.

No URL supplied; URL Trust Policy not applicable.

## Symptom

This is a code-quality (DRY) defect, not a runtime failure: every observation is a duplication or a redundant re-computation that works today but must be maintained in lockstep. Four instances:

1. `cmd_build` pre-validates source files (`cli.py:92-95`) even though `assemble_archive` performs the same check and raises (`archive.py:56-58`), with different message wording ("missing source file for X" vs "missing source file for member X").
2. `cli.py:74-78`, `85-89`, `97-106` are three identical `except → print → return 3` blocks for exceptions that all share the `ReleaseError` base.
3. `build_wheel` re-reads `pyproject.toml` via `resolve_version` (`wheel.py:45`) although the caller already resolved the version (`cli.py:75`).
4. The `wrap/` prefix-strip expression appears twice in `checks.py` (`:38` and `:67`) with divergent spelling (`len(prefix)` vs `len(wrap) + 1`).

Expected: one implementation per piece of knowledge (constitution DRY), single failure-handling path, version resolved exactly once.

## Reproduction

Static / by inspection — no runtime reproduction needed:

1. Open `src/schwab_mcp_release/cli.py:73-106` — observe the three identical except blocks and the pre-validation loop.
2. Compare `cli.py:92-95` with `src/schwab_mcp_release/archive.py:55-59` — same missing-source check, twice.
3. Observe `wheel.py:45` calling `resolve_version(project_root)` after `cli.py:75` already did.
4. Compare `checks.py:38` with `checks.py:67` — same strip expression, two spellings.

[NEEDS CLARIFICATION: none]

## Suspected Code Paths

- `src/schwab_mcp_release/cli.py:74-78, 85-89, 97-106` — three identical `print(f"error: {exc}", ...); return 3` blocks; all caught exceptions (`VersionError`, `WheelBuildError`, `ReleaseError`) share one base class.
- `src/schwab_mcp_release/cli.py:91-95` — validation loop over `sources.items()`; `source_map` is derived from the same `_CONTENT_MEMBER_TABLE` as `content_members` (verified in `allowlist.py:98-106`), so the loop checks exactly the paths `assemble_archive` re-checks at `archive.py:56-58`.
- `src/schwab_mcp_release/archive.py:56-58` — the authoritative missing-source check, already raising `ReleaseError`.
- `src/schwab_mcp_release/wheel.py:45` — `expected = wheel_name(resolve_version(project_root))` re-reads `pyproject.toml`.
- `src/schwab_mcp_release/checks.py:38, 67` — duplicated `wrap/` prefix-strip logic, spelled differently (`len(prefix)` vs `len(wrap) + 1`).
- `src/schwab_mcp_release/version.py:18`, `src/schwab_mcp_release/wheel.py:27` — confirm `VersionError(ReleaseError)` and `WheelBuildError(ReleaseError)`.

## Root Cause Hypothesis

The release-build command grew incrementally (spec 009): `cmd_build` defensively pre-validated inputs before delegating, each delegation site got its own except block instead of one around the delegated section, and `build_wheel` kept resolving the version itself to stay self-contained. No behavioral divergence exists today — the duplication is latent maintenance risk (a message or exit-code edit in one copy silently diverges from the other). Confidence: **high** (all four claims verified line-by-line against current source; the graph confirms production callers of `build_wheel`/`assemble_archive`/`source_map` are confined to `cmd_build`, so the consolidation is low-blast-radius).

## Proposed Remediation

**Preferred**: Apply the report's refactor, which the code structure already supports:

1. **One except block** in `cmd_build`: wrap `resolve_version` + `build_wheel` + `assemble_archive` in a single `try:` with `except ReleaseError as exc: print(f"error: {exc}", file=sys.stderr); return 3`. This subsumes the `VersionError` and `WheelBuildError` handlers (both subclass `ReleaseError` — verified). The dirty-tree guard (`return 2`) stays outside the try since it is not an exception path. Keep the docstring/main contract comment ("exit 3 build prerequisite failure") intact.
2. **Delete the duplicate validation loop** (`cli.py:92-95`): `assemble_archive` already raises `ReleaseError("missing source file for member …")`, which the new except block converts to exit 3. Safe because `source_map` covers exactly the content members (guaranteed by `test_release_allowlist.py::test_source_map_covers_exactly_the_content_members`).
3. **Pass the version through**: change to `build_wheel(project_root, version, out_dir)`; `wheel.py` drops the `resolve_version` import and uses `wheel_name(version)`. Update the in-function contract docstring.
4. **Extract `_relative_name(entry, wrap)`** in `checks.py`: `return entry[len(wrap) + 1 :] if entry.startswith(f"{wrap}/") else entry`; use it at both `:38` (via `wrap_dir(version)`-derived prefix — keep one prefix construction) and `:67`.

**Alternatives**:
- Minimal-touch: only collapse the except blocks and keep the pre-validation loop and `wheel.py` re-resolution. Trade-off: leaves two of the four duplications; little value for the churn.
- Introduce a `ReleasePipelineError` wrapper instead of relying on the shared base. Trade-off: a new exception class for no benefit — the base class already exists and is the designed seam.

**Files likely to change**:
- `src/schwab_mcp_release/cli.py`
- `src/schwab_mcp_release/wheel.py`
- `src/schwab_mcp_release/checks.py`
- `tests/unit/test_release_cli.py` (fake builders' signatures)
- `tests/unit/test_release_wheel.py` (direct `build_wheel` calls)
- `docs/tech-debt.md` (mark TD-015 Resolved, same commit)
- `docs/CHANGELOG.md` (per constitution: affected docs in the same commit)

**Tests to add or update**:
- Update fake builders in `test_release_cli.py` (`:153` `boom(project_root, out_dir)`, `:198` `build(project_root, out_dir)`) to the new `(project_root, version, out_dir)` signature — otherwise monkeypatching breaks silently.
- Update direct `build_wheel(...)` calls in `test_release_wheel.py` (`:25, 33, 56, 69, 76, 77`) to pass the version explicitly; add a case asserting the version passed in — not `pyproject.toml` — drives the expected wheel name.
- `test_exit_3_on_missing_source_file` (`test_release_cli.py:161-167`) should keep passing after the loop deletion (the `assemble_archive` message still contains the member path); keep it as the regression lock for behavior preservation.
- Add/keep a unit test that a `VersionError` surfaces as exit 3 through the single `except ReleaseError` path (existing `test_exit_3_when_version_unresolvable` covers it; it must remain green unchanged).
- Tests for `_relative_name`: top-level member, wrapped member, and non-wrapped entry (nested-wheel `!` names pass through unstripped).

## Risks & Considerations

- **Signature change is breaking for tests only**: `build_wheel` has no production caller besides `cmd_build` (graph-verified), but three test fakes pin the old two-arg signature.
- **Message drift**: after deleting `cli.py:92-95`, the missing-source message becomes the `archive.py` wording ("missing source file for member …"). Exit code (3) and the member path in stderr are preserved; `test_exit_3_on_missing_source_file` asserts the path, not the wording, so it stays green — but any consumer grepping for the exact old phrase would notice.
- **Behavior preservation is the whole point**: this is a pure DRY refactor; no exit-code, stdout-contract, or staging-cleanup change is acceptable. The stdout contract (`specs/009-mcp-release-packaging/contracts/build-command.md`) and FR-004 (stderr names the piece, never content) must hold.
- Low overall risk: confined to the release tooling, exercised by unit tests, no data or credential exposure.

## Open Questions

- [NEEDS CLARIFICATION: none]