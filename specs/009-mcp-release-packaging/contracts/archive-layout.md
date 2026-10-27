# Contract: Distribution Archive Layout

**Feature**: 009-mcp-release-packaging | **Date**: 2026-10-26

Authoritative allowlist for the contents of `schwab-mcp-<version>.zip`. This list is the single source of truth (DRY) for archive assembly (FR-002) and the completeness check (FR-008): the check requires every entry below to be present and requires that no additional top-level entry exists.

## Top-level layout

```text
schwab-mcp-<version>.zip
└── schwab-mcp-<version>/                # single top-level wrapping directory (unzip → cd target)
    ├── README.md                        # Overview + integrity verification pointer (FR-010) — VERBATIM copy of docs/release/README.md (single authored source)
    ├── dist/
    │   └── schwab_mcp-<version>-py3-none-any.whl   # Runtime wheel: ONLY package schwab_mcp (FR-003)
    ├── manuals/                         # English manuals copied from docs/release/ (FR-002, FR-006, FR-007)
    │   ├── installation.md
    │   ├── first-run-authentication.md
    │   ├── usage.md
    │   └── troubleshooting.md
    ├── install.sh                       # Prerequisite check + venv install script (FR-012, research D11)
    ├── manifest.json                    # Version, build_dirty, member inventory with sizes + sha256
    └── SHA256SUMS                        # sha256 of every member (recipient-side verification)
```

## Member rules

| Rule | Requirement |
|------|-------------|
| Top-level wrapping | Every member lives under the single top-level directory `schwab-mcp-<version>/` inside the zip, so `unzip` produces one folder to `cd` into |
| Wheel contents | Exactly the `schwab_mcp` runtime package + entry points (`schwab-mcp` console script). MUST NOT contain `schwab_mcp_release`, tests, specs, plans, or dev configuration (FR-003) |
| README | Archive-root `README.md` is a verbatim copy of `docs/release/README.md` — one authored source, no in-archive duplication |
| Manuals | The four task manuals present under `manuals/`, English, copied verbatim from `docs/release/` (FR-006) |
| `install.sh` | Checks Python ≥ 3.11, creates venv, installs wheel, verifies `schwab-mcp --help`; every failure prints an actionable message referencing the matching manual section (FR-012) |
| `manifest.json` | Fields per data-model: `version`, `build_dirty`, `members[]` (path, size, sha256) |
| `SHA256SUMS` | One `<sha256>  <member-path>` line per member, sorted by path |
| No secrets | No member may match the secret-scan rules (FR-004); scan failures name the member only |
| Determinism | Member timestamps normalized to a fixed value; members written in the order above (FR-011) |
| No credentials | Archive must never contain tokens, API keys, or env files with secrets; the recipient's token DB lives in `~/.schwab-mcp/` on their machine, never in the archive |

## Recipient flow (normative for the install script)

```sh
shasum -a 256 -c ../schwab-mcp-<version>.zip.sha256   # 1. verify outer checksum (manual step)
unzip schwab-mcp-<version>.zip
cd schwab-mcp-<version>
./install.sh                    # 2. prerequisites + install (actionable errors)
source .venv/bin/activate
schwab-mcp auth                 # 3. first-run authentication (manuals/first-run-authentication.md)
schwab-mcp serve                # 4. start stdio MCP server; connect AI client (manuals/usage.md)
```

Upgrade = re-running steps 1–2 with a newer archive: the wheel replaces the old install in place; `~/.schwab-mcp/tokens.db` is outside the install and therefore preserved (FR-015).

## Forbidden content (checked, build fails on match)

- Paths matching: `tests/`, `specs/`, `plans/`, `.git*`, `__pycache__/`, `*.egg-info/`, dev config (`pyproject.toml` itself, dev scripts)
- File names: `.env`, `*.pem`, `*token*db*`, `*secret*`, `*credential*`
- Text patterns in members: OAuth token/key shapes, `api_key =`, `app_key =`, bearer token literals (reported by member name only — never the content)