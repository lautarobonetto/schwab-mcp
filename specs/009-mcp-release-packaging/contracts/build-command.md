# Contract: Release Build Command

**Feature**: 009-mcp-release-packaging | **Date**: 2026-10-26

The maintainer-facing interface for producing a distribution package. This command lives in the maintainer-only package `schwab_mcp_release` and is NOT part of the shipped product.

## Invocation

```sh
uv run schwab-mcp-release build [--allow-dirty] [--output-dir DIR]
```

| Argument | Type | Default | Meaning |
|----------|------|---------|---------|
| `--allow-dirty` | flag | off | Permit building from a working tree with uncommitted changes; the manifest records `build_dirty: true` (research D4) |
| `--output-dir` | path | `dist/` | Directory that receives the archive and its checksum file |

## Inputs (implicit)

- Repository checkout at the current `pyproject.toml` version (source of truth for the package version).
- Manual set under `docs/release/` (see `manuals-set.md`).
- Allowlist contract in `archive-layout.md`.

## Outputs

On success, exactly two files are produced:

| File | Content |
|------|---------|
| `dist/schwab-mcp-<version>.zip` | The distribution archive (layout per `archive-layout.md`) |
| `dist/schwab-mcp-<version>.zip.sha256` | Single line: `<hex-sha256>  schwab-mcp-<version>.zip` |

On failure, no archive is emitted as valid: staging happens under `tmp/release-staging/`, which MUST be cleaned up on any failure (nothing partial survives outside `tmp/`), and the checksum file MUST NOT be written.

## stdout contract (stable, for tests and docs)

```text
BUILD schwab-mcp <version>
WHEEL  schwab_mcp-<version>-py3-none-any.whl
ARCHIVE members=<n> bytes=<size>
CHECKS completeness=PASS exclusion=PASS secrets=PASS
OUT    dist/schwab-mcp-<version>.zip
OUT    dist/schwab-mcp-<version>.zip.sha256
OK     build complete in <seconds>s
```

## Exit codes

| Code | Meaning | Contract |
|------|---------|----------|
| 0 | Success | Both output files exist; all checks passed |
| 1 | Validation failure | Message names the failing check and the offending/missing member: `MISSING: manuals/installation.md`, `DEV-MATERIAL: tests/…`, `SECRET: .env (name only)` — content of the offending file is never printed (credential safety) |
| 2 | Dirty working tree without `--allow-dirty` | Message: `working tree has uncommitted changes; pass --allow-dirty to build anyway` |
| 3 | Build prerequisite failure (wheel build error, missing docs/release manual on disk) | Message names the tool error or missing source file |

## Behavioral requirements (traceable)

- FR-001: single command produces the complete package.
- FR-005: version stamped from `pyproject.toml`; printed in the `BUILD` line.
- FR-008: completeness check fails naming the missing piece (exit 1).
- FR-009: exclusion + secret scans fail naming the offending item (exit 1).
- FR-011: same version + inputs → byte-equivalent archive (normalized timestamps, fixed member order).
- SC-002: full run < 60 s (covered by a performance test).

**Note on the `CHECKS` line**: the `completeness` field was delivered with US1; the `exclusion` and `secrets` fields landed with the US3 scans (tasks.md T015 asserted the US1-scope line during development, T032 extended it to the full contract above — shipped).

## Version visibility for recipients (FR-005)

After installation, `schwab-mcp --help` prints the package version so a recipient can report exactly what they run.