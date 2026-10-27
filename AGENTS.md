# AGENTS.md

Entry point for AI agents working **on the code** of this repo. (If
you're looking for how to *use* the MCP as an agent, go to
[docs/tools.md](docs/tools.md).)

## Authority

The project constitution is
[`.specify/memory/constitution.md`](.specify/memory/constitution.md) —
**read it before planning or implementing anything**. It is not
negotiable and takes precedence over any other practice. Non-normative
summary:

- **Mandatory TDD**: tests first (Red → Green → Refactor); bug fixes
  start with a regression test that reproduces the defect.
- **DRY / Reuse Before Creation / KISS**: one implementation per piece
  of knowledge; reuse before creating; the simplest thing that works.
- **Measurable budgets**: performance and token-usage tests per
  feature; growth requires recorded justification.
- **Fixed layout**: code in `src/`, tests in `tests/`, documentation in
  `docs/`, scratch **only** in `tmp/` (git-ignored). Nothing outside.
- **Credential safety**: tokens/secrets never in logs, outputs, or git.
- **Commits**: full suite green and no skipped tests; message listing
  the changes; **affected documentation updated and included in the
  same commit**.

## Trade analysis

When analyzing trades over a given period, if any trade or trade chain
doesn't make sense (position or balance that doesn't reconcile, a sale
without a prior purchase, etc.), **do not treat it as missing or
erroneous data**: the chain most likely started **before** the analyzed
period. Proceed as follows:

1. Identify the orphan trade within the period.
2. Search for the opening trade using the history **filtered by
   instrument** (`symbol`), in **earlier** time windows, stepping
   backward successively (the tool accepts up to 1 year per request).
3. Declare the search strategy **before** each request (filter, window,
   and why), so the process is auditable.
4. Escalate to an **unfiltered** request only if the filtered sweep
   exhausted its reach without finding the opening trade: it may be a
   roll into a different symbol, an assignment, or a transfer between
   accounts, which the symbol filter doesn't capture.
5. Repeat until you reconstruct the opening transaction that explains
   the initial state (purchase, assignment, deposit, transfer, etc.).
6. Re-analyze the period with full context, so the chain makes sense
   end to end before drawing conclusions.

## Market data sources (MCP)

When analyzing the portfolio, split queries by source:

| Need | MCP |
|------|-----|
| Positions, transactions, option chains | `schwab` |
| Earnings calendar, dividends (ex-date, record date, payment), balance sheets and financial statements, ratios | `fmp` (remote, configured in `~/.config/opencode/opencode.json`) |

- Schwab **does not** expose earnings calendar, dividends, or fundamentals: those queries always go through FMP.
- FMP earnings dates are **estimates**; if the data is critical, confirm against the company's IR.
- The FMP API key lives only in the OpenCode global config; never in logs, outputs, or git (credential safety).

## Workflow

Spec Kit: `/speckit.specify` → `/speckit.plan` → `/speckit.tasks` →
`/speckit.implement` → `/speckit.converge`. Each feature's artifacts
live in `specs/<NNN-feature>/` (spec, plan, tasks, contracts,
quickstart). Before implementing, run `/speckit.analyze` to detect
inconsistencies between spec/plan/tasks.

## Commands

```sh
uv sync                        # set up the environment
uv run pytest                  # full suite (commit gate: green, 0 skipped)
uv run schwab-mcp --help       # CLI: auth, serve, renew, auth-status
```

CI (`.github/workflows/ci.yml`) enforces the same gate (`uv sync && uv run
pytest`) on every push to `main` and every pull request.

## Sources of truth (don't duplicate here)

| Topic | Where |
|-------|-------|
| Governance and gates | [`.specify/memory/constitution.md`](.specify/memory/constitution.md) |
| Interface for AI agents consuming the MCP | [`docs/tools.md`](docs/tools.md) |
| Usage and installation (humans) | [`docs/usage.md`](docs/usage.md) · [`docs/installation.md`](docs/installation.md) |
| Change history | [`docs/CHANGELOG.md`](docs/CHANGELOG.md) |
| Release and packaging for recipients | [`docs/release-maintenance.md`](docs/release-maintenance.md) |
| Command/event contracts | [`specs/*/contracts/`](specs/) |