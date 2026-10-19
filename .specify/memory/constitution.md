# Schwab MCP Constitution

## Core Principles

### I. Test-First Development (NON-NEGOTIABLE)

Test-Driven Development (TDD) is mandatory for all production code. The
workflow is always: **tests are written first** → they MUST fail (Red) →
minimal implementation is written to pass them (Green) → code is refactored
(Refactor). No production code may exist without a preceding failing test
that motivates it. Bug fixes MUST begin with a regression test that
reproduces the reported defect before any remediation is written. A feature
without tests that were written first is incomplete and non-compliant.

### II. Don't Repeat Yourself (DRY)

Every piece of knowledge within the system MUST have a single, unambiguous,
authoritative representation. Duplicated logic, constants, schemas, API
request/response handling, configuration parsing, or error mapping MUST NOT
be introduced. When duplication is discovered, it MUST be consolidated into
one source of truth that other code references. Rationale: duplication in a
financial-integration codebase multiplies the surface area for inconsistent
behavior (https://en.wikipedia.org/wiki/Don%27t_repeat_yourself).

### III. Reuse Before Creation

Before writing any new code, developers and agents MUST first search for and
evaluate existing solutions, in this order: (1) code already present in this
repository, (2) the standard library, (3) well-established, actively
maintained third-party libraries, (4) Spec Kit templates and existing project
tooling. Creating a new module, utility, abstraction, or dependency is
justified only when no suitable existing solution exists, and the reason MUST
be stated (e.g., in the plan or PR description) when the choice is not
obvious.

### IV. Simplicity (KISS)

The simplest solution that satisfies the current, stated requirements MUST be
preferred over any more elaborate alternative. YAGNI applies: speculative
features, premature generalization, speculative abstractions, and
"just-in-case" configuration MUST NOT be built. Every added layer of
complexity (new dependency, new abstraction, new configuration surface) MUST
be justified in writing; if a straightforward implementation exists, it
wins. Reference: https://en.wikipedia.org/wiki/KISS_principle

### V. Efficiency & Cost Awareness (Performance and Token Budget)

Efficiency is a first-class, testable requirement, not an afterthought.
Every feature MUST be accompanied by:

- **Performance tests** that assert the expected runtime behavior of the
  MCP server (tool invocation latency, I/O handling) against explicit
  budgets.
- **Token-usage tests** that assert the size of tool outputs, so that what
  an LLM consumes per invocation stays within declared budgets.

MCP tool responses MUST be designed to minimize token consumption: return
only the fields needed for the task, prefer compact formats, paginate or
truncate large result sets deterministically, and document the expected
payload size for each tool. Changes that measurably increase token usage or
latency beyond declared budgets MUST NOT be accepted without an explicit,
recorded justification.

## Repository Layout

The repository layout is fixed and non-negotiable. Every file created in
this project MUST live in one of the following directories, located at the
repository root:

| Directory | Purpose |
|-----------|---------|
| `src/`    | All source code, without exception. |
| `tests/`  | All tests (unit, integration, performance, token-usage), without exception. |
| `docs/`   | All documentation, without exception. |
| `tmp/`    | Every file or directory that must be created temporarily (scratch files, caches, intermediate artifacts, throwaway scripts, local experiment output). |

Rules:

- Source code MUST NOT be placed outside `src/`; tests MUST NOT be placed
  outside `tests/`; documentation MUST NOT be placed outside `docs/`.
- Temporary artifacts MUST NEVER be created outside `tmp/`. Agents and
  developers MUST NOT write scratch files to the repository root or to
  system-wide locations; the approved scratch location is `tmp/`.
- `tmp/` MUST be listed in `.gitignore` and MUST NEVER be committed to Git.
  No file inside `tmp/` may ever appear in version control, in a release, or
  in a commit.
- Tooling configuration that must live at the repository root (e.g.,
  `pyproject.toml`, `README.md`, `.gitignore`) is exempt from this layout,
  but any code, test, or documentation content referenced by it still
  belongs in its designated directory.

## Project Context & Constraints

This project is a **local Model Context Protocol (MCP) server of type
`stdio`** that integrates with the **Charles Schwab APIs** to access trading
account information. The following constraints are non-negotiable:

- **Local-only transport**: the server communicates exclusively over stdio.
  It MUST NOT open network sockets for inbound connections or expose any
  HTTP server surface.
- **Credential safety**: Schwab API credentials, OAuth tokens, and refresh
  tokens MUST never be committed to version control, written to logs, or
  emitted in tool outputs. They are loaded from local, user-controlled
  secure storage only.
- **Read/write discipline**: operations that move money or place orders MUST
  be explicitly modeled as separate, clearly named tools, and their behavior
  MUST be covered by tests before release.

## Development Workflow & Quality Gates

All changes follow the Spec Kit flow (`/speckit.specify` →
`/speckit.plan` → `/speckit.tasks` → `/speckit.implement` →
`/speckit.converge`) and MUST pass these gates before completion:

1. **Test-first gate**: tests were written and failed before the
   corresponding implementation exists (TDD, Principle I).
2. **Test suite gate**: the full test suite passes with no skipped tests.
3. **Performance gate**: performance tests pass within declared budgets
   (Principle V).
4. **Token-usage gate**: token-usage tests pass; any growth in payload size
   is justified in the change description (Principle V).
5. **DRY/KISS review**: the change contains no new duplication and no
   unjustified complexity; reuse opportunities were evaluated (Principles
   II–IV).
6. **Layout gate**: every new or moved file is inside its designated
   directory (`src/`, `tests/`, `docs/`); every temporary artifact is inside
   `tmp/`; `tmp/` remains git-ignored (Repository Layout).

### Commit Discipline

Every `git commit` MUST satisfy the following rules:

- **Green-before-commit**: the full test suite MUST pass at the moment of
  the commit. A commit MUST NOT be created while any test fails or is
  skipped; if tests fail, the work is not commit-ready.
- **Descriptive commit messages**: every commit message MUST include, in
  addition to its summary line, a description that lists all the changes
  being committed (files, features, or concerns included in that commit).
  A commit whose message does not enumerate its changes is non-compliant
  and MUST NOT be pushed.

These rules apply to every contributor and agent performing commits, and
are part of the compliance review.

## Governance

- This constitution supersedes all other development practices for this
  project. Any conflict between feature plans, task breakdowns, or ad-hoc
  requests and this document is resolved in favor of the constitution.
- **Amendments** require: a documented rationale, a semantic version bump
  (MAJOR for principle removals/redefinitions, MINOR for new principles or
  materially expanded guidance, PATCH for clarifications), and an updated
  Last Amended date.
- **Compliance review**: every change MUST be reviewed against the quality
  gates above; violations block completion of the corresponding
  speckit-implement step.
- Runtime development guidance lives in this file and in the active Spec
  Kit plan documents; agents MUST consult the constitution at the start of
  plan and implement phases.

**Version**: 1.2.0 | **Ratified**: 2026-10-19 | **Last Amended**: 2026-10-19
