# Data Model: MCP Release Packaging

**Feature**: 009-mcp-release-packaging | **Date**: 2026-10-26

Entities involved in building, validating, distributing, and installing the release package. Field types are indicative; implementation binds them to Python/stdlib structures.

## Entities

### BuildRequest

The maintainer's intent to produce one distribution package.

| Field | Type | Rules |
|-------|------|-------|
| version | string | MUST equal the `project.version` in `pyproject.toml` (single source of truth, FR-005) |
| source_tree_state | enum(`clean`, `dirty`) | `dirty` requires the `--allow-dirty` override or the build fails (D4) |
| allow_dirty | bool | default `false` |
| output_dir | path | default `dist/`; must exist or be creatable |

**Validation rules**: version resolvable; dirty tree without override → fail (exit code 2).

### BuildResult

Outcome of one execution of the build command.

| Field | Type | Rules |
|-------|------|-------|
| status | enum(`success`, `failed`) | `failed` MUST name the offending check or missing piece (FR-008/FR-009) |
| failure_reason | string \| null | required when `failed`; names member/check, never prints file content (credential safety) |
| archive_path | path \| null | required when `success`; `<output_dir>/schwab-mcp-<version>.zip` |
| checksum_path | path \| null | required when `success`; sibling `.sha256` file (FR-010) |
| dirty_marker | bool | `true` when built with `--allow-dirty`; recorded in Manifest |

**State transitions**: `success` is reached only after ALL of: wheel built → archive assembled → completeness check passed → exclusion scan passed → secret scan passed. Any earlier failure aborts with no archive emitted as valid.

### DistributionPackage (the archive)

The artifact handed to recipients. Contents are governed by the allowlist in `contracts/archive-layout.md`.

| Field | Type | Rules |
|-------|------|-------|
| version | string | stamped from BuildRequest; discoverable post-install (`schwab-mcp --help` output shows version, FR-005) |
| members | list[Member] | exactly the allowlist set; no extra top-level members (FR-003) |
| manifest | Manifest | inner self-description |
| determinism | — | member timestamps normalized; fixed member order (FR-011) |

### Member

One file inside the DistributionPackage.

| Field | Type | Rules |
|-------|------|-------|
| path | string (archive-relative, under the wrapping top-level directory `schwab-mcp-<version>/`) | matches allowlist entry |
| size | int | > 0 for required members |
| sha256 | hex string | computed at manifest time; verified by recipient per manual |

### Manifest

Inner inventory shipped inside every archive (`manifest.json`).

| Field | Type | Rules |
|-------|------|-------|
| version | string | package version |
| build_dirty | bool | dirty-tree marker (D4) — records the actual working-tree state at build time |
| members | list[Member] | every content member with size + sha256 (the 7 shipped files; `manifest.json`/`SHA256SUMS` are the inventories themselves and cannot list their own hash — the outer `.zip.sha256` covers the complete archive) |

### Manual

One recipient-facing document under `docs/release/`, shipped at `manuals/<name>` inside the archive.

| Field | Type | Rules |
|-------|------|-------|
| name | enum(`README`, `installation`, `first-run-authentication`, `usage`, `troubleshooting`) | full set is mandatory (FR-006); missing one fails the completeness check |
| language | `en` | fixed by clarify decision (English only) |
| required | bool | all five are required |

**Coverage obligations**: per `contracts/manuals-set.md` — prerequisites, install, first-run auth, AI-client connection, daily use + renewal behavior, troubleshooting, upgrade-in-place (FR-015), integrity verification (FR-010).

### ExclusionRule

A scan rule enforcing FR-003/FR-004 over final archive members.

| Field | Type | Rules |
|-------|------|-------|
| kind | enum(`dev_material`, `secret`) | dev: tests/specs/plans/dev-config/editable-source patterns; secret: `.env`-style files, credential-named files, credential-content patterns |
| action | `fail` | match → build fails naming the member (FR-009) |
| report_style | name-only | never emits matched content (credential safety) |

### RecipientInstallation

The installation created on the recipient machine from a DistributionPackage.

| Field | Type | Rules |
|-------|------|-------|
| version | string | from installed wheel metadata |
| prerequisites | enum(`met`, `unmet`) | Python ≥ 3.11 checked by install script (FR-012, D11) |
| credentials | path | recipient-owned `~/.schwab-mcp/tokens.db` (default; configurable) — OUTSIDE the installation, hence preserved by in-place upgrade (FR-015) |

**State transitions**: `uninstalled → installed → authenticated → serving`; upgrade = `installed(v_n) → installed(v_n+1)` with credentials untouched. Prerequisite failure blocks installation with actionable message.

## Relationships

- BuildRequest --produces--> BuildResult --emits--> DistributionPackage (contains Members, one Manifest, five Manuals)
- ExclusionRule --validates--> DistributionPackage (pre-success gate)
- DistributionPackage --installs-to--> RecipientInstallation (in-place upgrade path between versions)
- Checksum file --verifies--> DistributionPackage (recipient-side, per manual)

## Key invariants

1. Shipped wheel contains exactly the `schwab_mcp` runtime package — never `schwab_mcp_release` (FR-003).
2. No archive member may contain secret material; scan failures name the member only (FR-004, credential safety).
3. Two builds from the same version + inputs produce byte-equivalent archives (FR-011).
4. The archive is emitted only when every check passes; failures emit nothing valid (FR-008/FR-009).
5. Recipient credentials never live inside the installation directory, so upgrades cannot destroy them (FR-015, credential safety).