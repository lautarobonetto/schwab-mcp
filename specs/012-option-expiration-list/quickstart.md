# Quickstart: `get_option_expiration_chain` (012)

End-to-end validation guide. Run from the repository root after
implementation. Prerequisites: `uv sync` done; provider credentials
configured (`~/.schwab-mcp/env`); the unit/integration suites do not need
live credentials.

## 1. Run the feature's tests (no live credentials needed)

```sh
uv run pytest tests/unit/test_option_expirations.py \
              tests/integration/test_option_expirations.py \
              tests/performance/test_option_expirations_budgets.py -v
```

Expected: all green, **0 skipped**. The suites prove:

- unit — mapping and ordering (data-model §2), DTE computation (calendar
  days from today), same-date entries kept separately with
  `settlement_type`, DTE ceiling filter (`dte ≤ dte_max_effective`),
  `no_expirations_in_range` and `no_options_listed` outcomes, validation
  errors before any upcall, `extended=true` passthrough.
- integration — exactly **one** provider invocation per scenario
  (SC-004); the shared outcome envelope; `filters` echo with
  `dte_max_effective` (SC-005).
- performance/token — dense 60-entry fixture ≤ 1,000 tokens (SC-001,
  estimator `len(json.dumps(..., separators=(",", ":")))/4`); latency
  within the declared budget (SC-002).

## 2. Full suite (commit gate)

```sh
uv run pytest
```

Expected: green, 0 skipped — the constitution's commit gate.

## 3. Live smoke test (needs valid credentials)

Start the server and call the tool through your MCP client:

```json
{"name": "get_option_expiration_chain", "arguments": {"symbol": "AAPL"}}
```

Expected: `outcome: "ok"`, `filters.dte_max_effective == 60`, ascending
`expiration_date` list with `dte` and `settlement_type`, no
strikes/quotes/greeks anywhere in the curated output, and
`expiration_count == len(expirations)`.

Window variants:

```json
{"name": "get_option_expiration_chain", "arguments": {"symbol": "AAPL", "dte_max": 30}}
```

→ only entries with `dte ≤ 30`; `filters.dte_max_effective == 30`.

```json
{"name": "get_option_expiration_chain", "arguments": {"symbol": "AAPL", "dte_max": 365}}
```

→ accepted (no hard upper limit — clarification 2026-11-03 Q1);
`dte_max_effective == 365`.

```json
{"name": "get_option_expiration_chain", "arguments": {"symbol": "SPX"}}
```

→ same-date entries appear as separate rows distinguished by
`settlement_type` (AM/PM), never merged (clarification Q2 option B).

Failure shapes (contracts/mcp-tools.md §3–§4): a nonsense symbol returns
the structured `no_options_listed` outcome (or the provider's mapped
error), `dte_max: 0` returns a validation error naming `>= 1`, and
`symbol: ""` fails before any upstream call.

## 4. Documentation check (commit gate)

The delivery commit must include the updated `docs/tools.md` (new tool
section, agent guidance, budgets) and `docs/CHANGELOG.md` entry —
constitution Commit Discipline.