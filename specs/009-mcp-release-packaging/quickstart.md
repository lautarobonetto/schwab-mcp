# Quickstart: MCP Release Packaging — Validation Guide

**Feature**: 009-mcp-release-packaging | **Date**: 2026-10-26

Runnable scenarios that prove the feature end-to-end. References: [build-command contract](contracts/build-command.md) · [archive layout](contracts/archive-layout.md) · [manuals set](contracts/manuals-set.md) · [data model](data-model.md).

## Prerequisites (maintainer machine)

- This repository checked out at the feature branch with a clean working tree (`git status` shows no changes).
- `uv` available; existing test suite green (`uv run pytest`).

## Scenario 1 — Build succeeds and emits a complete package (US1, FR-001, FR-002, FR-005)

```sh
uv run schwab-mcp-release build
```

Expected:
- stdout matches the stable `BUILD … OK build complete in <s>s` contract (exit 0)
- runtime < 60 s (SC-002)
- `dist/schwab-mcp-<version>.zip` and `dist/schwab-mcp-<version>.zip.sha256` exist, with `<version>` equal to `pyproject.toml`'s `project.version`

## Scenario 2 — Archive contents are complete and clean (US1, US3, FR-002, FR-003, FR-004)

```sh
unzip -l dist/schwab-mcp-<version>.zip        # single wrapping dir schwab-mcp-<version>/ containing the allowlist set
unzip -p dist/schwab-mcp-<version>.zip schwab-mcp-<version>/manifest.json   # version, build_dirty=false, all members listed
```

Expected:
- one wrapping top-level directory `schwab-mcp-<version>/` containing exactly: wheel (`schwab_mcp` runtime only — no `schwab_mcp_release`), root `README.md` (verbatim copy of `docs/release/README.md`), 4 manuals under `manuals/`, `install.sh`, `manifest.json`, `SHA256SUMS`
- zero dev-material paths (`tests/`, `specs/`, `plans/`, `__pycache__/`, `.git*`) and zero secret-bearing members

## Scenario 3 — Built-in checks fail loudly (US1, FR-008, FR-009)

- Temporarily empty a manual from `docs/release/` (e.g., `troubleshooting.md`) → build exits 1 printing `MISSING: manuals/troubleshooting.md`, no checksum file written. Restore the manual. (A manual *deleted* from disk is a build prerequisite failure instead: exit 3 naming the missing source file, per the build-command contract.)
- Add a file that trips the secret scan (e.g., a stray secret literal among archive inputs) → build exits 1 naming the member (name only, no content). Remove it.

## Scenario 4 — Dirty tree guard (FR-005, edge case, research D4)

```sh
echo "# scratch" >> README.md
uv run schwab-mcp-release build            # exit 2: uncommitted changes message
uv run schwab-mcp-release build --allow-dirty   # exit 0; manifest.json shows build_dirty=true
git checkout README.md
```

## Scenario 5 — Reproducibility (FR-011)

```sh
uv run schwab-mcp-release build
shasum -a 256 dist/schwab-mcp-<version>.zip
uv run schwab-mcp-release build
shasum -a 256 dist/schwab-mcp-<version>.zip   # identical digest
```

## Scenario 6 — Recipient install from the package only (US2, FR-006, FR-012, SC-001)

On a machine with Python ≥ 3.11 but no prior trace of this project:

1. Verify outer checksum per the archive-root `README.md`: `shasum -a 256 -c schwab-mcp-<version>.zip.sha256` → OK
2. Unzip and `cd schwab-mcp-<version>`; run `./install.sh` → prerequisites verified, venv created, wheel installed; `schwab-mcp --help` prints version
3. Follow `manuals/first-run-authentication.md`: `schwab-mcp auth` with own Schwab credentials → tokens stored in `~/.schwab-mcp/tokens.db` only
4. Connect an AI client per `manuals/usage.md`; invoke a read-only tool → correct data returned
- Total guided time target: ≤ 15 minutes (SC-001)

## Scenario 7 — In-place upgrade preserves credentials (FR-015)

With Scenario 6 installed and authenticated:

1. Build a bumped version (edit `pyproject.toml` version), run the build, hand the new archive to the same machine
2. Re-run checksum verify → unzip → `./install.sh` → `schwab-mcp --help` shows the new version
3. `schwab-mcp auth-status` still reports valid credentials — the old `~/.schwab-mcp/tokens.db` was preserved (it lives outside the installation)

## Scenario 8 — Automated suite gates

```sh
uv run pytest
```

Expected: full suite green, 0 skipped, including new unit tests (build command contract, archive allowlist assembly, checks/manifest behavior) and one `@pytest.mark.performance` test asserting build < 60 s. Token-usage gate: N/A for this feature — no MCP tool outputs are added or changed (justification recorded in plan.md).