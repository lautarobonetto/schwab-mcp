# Contract: Recipient Manuals Set

**Feature**: 009-mcp-release-packaging | **Date**: 2026-10-26

Defines the mandatory manual set shipped in every archive (`manuals/`), its language, audience, and coverage obligations (FR-006, FR-007). The completeness check treats a missing manual as a build failure.

## Common obligations

- **Language**: English only (clarify session Q3, 2026-10-26).
- **Audience**: a technical-but-non-developer Schwab account owner; no knowledge of the project's development history or internals is assumed (FR-007).
- **Tone**: task-oriented, step-by-step, each step verifiable by an expected outcome.

## Mandatory manuals

### 1. `README.md` — package overview

**Ships at**: archive ROOT (`README.md`), as a verbatim copy of `docs/release/README.md` — the other four manuals ship under `manuals/`.

| Obligation | Detail |
|------------|--------|
| What this package is | Local stdio MCP server for Charles Schwab account data |
| Package version visibility | Where the version is shown (`schwab-mcp --help`) (FR-005) |
| Integrity verification | How to verify the outer `.sha256` before installing (FR-010) |
| Reading order | Pointer to the other four manuals |

### 2. `installation.md` — prerequisites + install + upgrade
| Obligation | Detail |
|------------|--------|
| Prerequisites (FR-012) | Python ≥ 3.11; how to check; how to install if missing |
| Install steps | Unzip → `install.sh` → activate venv → `schwab-mcp --help` works; expected outcomes at each step |
| Prerequisite failure | What each `install.sh` error means and how to resolve it |
| Upgrade in place (FR-015) | Installing a newer archive over an existing installation; stored credentials (`~/.schwab-mcp/tokens.db`) are preserved automatically |

### 3. `first-run-authentication.md`
| Obligation | Detail |
|------------|--------|
| Schwab app credentials | Where the recipient obtains/registers their own Schwab API credentials |
| `schwab-mcp auth` flow | Step-by-step, expected browser/auth outcomes |
| Credential storage | Credentials stored only in the recipient's local secure storage (`~/.schwab-mcp/tokens.db`); never in the package, logs, or outputs (FR-014, credential safety) |
| Failure symptoms | Missing/wrong credentials, browser-step failure — resolution paths without maintainer contact |

### 4. `usage.md` — daily use
| Obligation | Detail |
|------------|--------|
| Connecting an AI client | Configuring the recipient's AI client application to launch `schwab-mcp serve` over stdio |
| Available tools | What each tool does (positions, transactions, option chains) and typical prompts |
| Token renewal behavior | Access tokens renew automatically; what (if anything) the recipient must do (FR-002/FR-013) |
| Configuration | Env-based options (e.g., token DB path) as supported by the runtime |

### 5. `troubleshooting.md`
| Obligation | Detail |
|------------|--------|
| Symptom → resolution table | Missing prerequisite; auth failure; AI client cannot connect; expired/invalid credentials; upgrade problems |
| Diagnostic commands | `schwab-mcp auth-status`, how to read its output safely (no secrets printed) |
| Escalation | What to report to the maintainer (version from `schwab-mcp --help`, symptom, steps) — and what NOT to share (tokens/credentials) |

## Acceptance mapping

| Spec requirement | Covered by |
|------------------|------------|
| FR-006 (manual coverage list) | Manuals 2–5 sections above |
| FR-007 (non-developer audience) | Common obligations |
| FR-010 (integrity verification) | Manual 1 |
| FR-012 (prerequisites, actionable failures) | Manual 2 + `install.sh` messages |
| FR-013 (runtime guarantees documented) | Manuals 3–4 (local-only stdio, credential storage, renewal) |
| FR-014 (credential-safety instruction) | Manual 3 |
| FR-015 (in-place upgrade, credentials preserved) | Manual 2 |
| SC-001 (guided install ≤ 15 min) | Manuals 1–3 as a continuous path |
| SC-005 (self-service troubleshooting ≥ 90%) | Manual 5 |