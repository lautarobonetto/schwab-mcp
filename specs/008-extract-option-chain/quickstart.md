# Quickstart: `get_option_chain` (008)

End-to-end validation guide. Full contract:
[contracts/mcp-tools.md](contracts/mcp-tools.md). Data model:
[data-model.md](data-model.md).

## Prerequisites

```sh
uv sync                        # environment
uv run schwab-mcp auth         # humans only; once, if there is no token
uv run schwab-mcp auth-status  # must report a current token
```

## S1 — Default chain (US1)

1. `uv run schwab-mcp serve` in a terminal.
2. Invoke the tool with only `symbol` (e.g. `"AAPL"`), no filters.
3. Verify in the response:
   - `filters.dte_max_effective == 60` and all `expiration.dte ≤ 60`;
   - both legs (`call` and `put`) present per strike row;
   - ≤ `2 × max_strikes` (100) strike rows per expiration, ordered by
     strike, centered on `atm_strike`;
   - each leg with the `contract_fields` columns and the 5 Greeks
     (`delta`..`rho`) reported or explicit `null`;
   - a single response (no pagination) and `underlying_price` present.

## S2 — Target delta + type (US2)

1. Invoke with `symbol`, `option_type="puts"`, `delta_target=0.20`.
2. Verify: only `put` legs; per expiration ≤ 5 strikes around the
   contract with delta ≈ -0.20 (|delta| ≈ 0.20); no strikes outside that
   window.
3. Repeat with `option_type="both"` and `delta_target=0.20`: up to 5
   CALL strikes **and** up to 5 PUT strikes per expiration (per-type
   window, clarification 2026-10-23).
4. **Live validation (SC-005)**: repeat steps 1–3 against the real chain
   of a liquid underlying (with a current token) and confirm the same
   invariants; the suite fixtures cover the edges (delta at the boundary
   of the curve, missing strikes).

## S3 — Explicit limits (US3)

1. `max_strikes=10`: at most 10 strike rows per side of the money per
   expiration.
2. `dte_max=7`: only expirations with `dte ≤ 7`; if the nearest
   expiration expires farther out → structured
   `no_expirations_in_range` result, not a generic error.
3. `dte_max=120`: includes expirations farther out than the default.

## S4 — Edge cases

| Invocation | Expected |
|---|---|
| `symbol="ZZZZZZ"` (no options) | structured `no_options_listed` |
| `delta_target=1.5` | validation error before upcall |
| `max_strikes=0` | validation error |
| `option_type="strangles"` | validation error |
| Source down (see `tests/integration/test_failures.py` for the pattern) | structured error without partial chain (FR-013) |
| Entire expiration without data in the payload | structured error without partial chain |

## Test gates

```sh
uv run pytest tests/unit/test_options_chain_validation.py \
              tests/unit/test_options_chain_mapping.py \
              tests/unit/test_options_chain_filters.py \
              tests/unit/test_options_chain_delta.py   # unit
uv run pytest tests/integration/test_options_chain.py  # integration
uv run pytest tests/performance/test_options_chain_budgets.py -m performance  # budgets
uv run pytest                                          # full suite: green, 0 skipped
```

## References

- Tool registration: `src/schwab_mcp/server.py` (wrapper pattern of
  `get_open_positions` / `get_transaction_history`).
- Agent consumption: `docs/tools.md` (new section of the tool, included
  in the feature commit).