# Development guide

How to set up a machine and how to work **on the code** of this
project. It complements (does not replace) the project constitution and
the agent entry point:

| Topic | Where |
|-------|-------|
| Project constitution (**read first**) | [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) |
| Roadmap: project direction and planned specs | [`.specify/memory/roadmap.md`](../.specify/memory/roadmap.md) |
| Entry point for AI agents working on the code | [`AGENTS.md`](../AGENTS.md) |
| Interface for AI agents consuming the MCP | [`docs/tools.md`](./tools.md) |

## What to install

| Tool | Why | Install |
|------|-----|---------|
| [uv](https://docs.astral.sh/uv/) | Python project and environment manager; runs every command in this guide | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (macOS/Linux) or `irm https://astral.sh/uv/install.ps1 \|iex` (Windows) |
| Python ≥ 3.11 | Runtime requirement (`requires-python` in `pyproject.toml`); uv manages the interpreter for you | `uv python install 3.11` |
| git | Version control | Any recent version |
| [OpenCode](https://opencode.ai) | The coding-agent harness this project is developed with | See [opencode.ai/docs](https://opencode.ai/docs) |

OpenCode loads the project conventions automatically from
`AGENTS.md` and `.opencode/rules/*.md`. For the full agent-assisted
workflow you also need, in your OpenCode **global** config
(`~/.config/opencode/opencode.json`):

- **codebase-memory-mcp**: keeps a knowledge graph of the codebase
  (symbol search, call tracing, architecture overview). Used through
  its `search_graph` / `trace_path` / `get_code_snippet` tools instead
  of raw grep wherever possible. Configure it as an MCP server in the
  global config.
- **Spec Kit commands**: already included in this repository at
  `.opencode/commands/speckit.*` — nothing to install; they appear as
  `/speckit.*` commands inside OpenCode.

Optional but recommended: the **FMP MCP server** in the global config
if you work on features that touch market data beyond Schwab's surface
(earnings, dividends, fundamentals). The FMP API key lives **only** in
the global OpenCode config — never in logs, outputs, or git.

## Setup

```sh
git clone https://github.com/lautarobonetto/schwab-mcp.git
cd schwab-mcp
uv sync                          # creates .venv and installs everything
uv run pytest                    # verify the suite is green on a fresh clone
uv run schwab-mcp auth           # interactive authorization (humans only)
uv run schwab-mcp serve          # run the MCP server over stdio
```

## How to develop

Development is spec-driven with **Spec Kit** and governed by the
constitution. The workflow:

1. **Read the constitution** (`.specify/memory/constitution.md`) before
   planning or implementing anything. Its highlights:
   mandatory **TDD** (tests first: Red → Green → Refactor; bug fixes
   start with a regression test), **DRY/KISS**, measurable performance
   and token budgets per feature, fixed layout (`src/`, `tests/`,
   `docs/`, scratch only in `tmp/`), credential safety, and a green
   suite with no skipped tests as the commit gate.
2. **Spec the feature** with the Spec Kit pipeline — each feature gets
   a numbered directory under `specs/<NNN-feature>/`:

   ```text
   /speckit.specify  → draft the spec from the user intent
   /speckit.plan     → technical plan against the constitution
   /speckit.tasks    → break the plan into ordered tasks
   /speckit.analyze  → detect inconsistencies spec/plan/tasks (before implementing)
   /speckit.implement→ execute the tasks (TDD per task)
   /speckit.converge → reconcile docs and reality after the change
   ```

   Discovery (`/speckit.assess.*`) and bug-flow (`/speckit.bug.*`)
   commands are also available for idea assessment and defect fixing.
   Before speccing a new feature, check the **roadmap**
   (`.specify/memory/roadmap.md`) — the planned-specs ledger records
   intended features, their scope notes, and cross-cutting decisions so
   they are not lost. Ratify new direction decisions and planned specs
   there with the `/speckit.roadmap.*` commands (`write`, `sync`,
   `brief`, `debrief`), and move a ledger entry to `specced` when its
   Spec Kit pipeline starts.
3. **Use the knowledge graph**: with codebase-memory-mcp, prefer
   `search_graph` / `trace_path` / `get_code_snippet` / `query_graph`
   over grep for structural code discovery; fall back to grep for
   string literals and non-code files.
4. **Tests first, always.** The suite lives in `tests/`
   (`unit/`, `integration/`, `performance/`); the commit gate is
   `uv run pytest` fully green with **zero skipped tests**.
5. **Commit**: full suite green, message listing the changes, and any
   affected documentation (`docs/`, `AGENTS.md`, `docs/tools.md`,
   contract files under `specs/`) updated **in the same commit**.
   CI enforces the same gate on every push to `main` and every PR.

## Project layout

```text
src/                  package code (CLI + MCP server + Schwab client)
tests/                unit / integration / performance suites
docs/                 human documentation (usage, installation, tools)
specs/<NNN-feature>/  Spec Kit artifacts per feature (spec, plan, tasks, contracts)
.specify/             project governance: constitution and roadmap in memory/, extensions, templates
.opencode/            agent rules and speckit commands
tmp/                  scratch space (git-ignored — nothing permanent here)
```