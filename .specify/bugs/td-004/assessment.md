# Bug Assessment: TD-004 — Error envelopes and `ToolError` boundary divergent (DRY, live divergence)

- **Slug**: td-004
- **Created**: 2026-11-04
- **Source**: pasted text (tech-debt item TD-004)
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

Pasted tech-debt report, two claims:

1. `price_history.py:147-182` duplicates the four envelope helpers from
   `quotes.py:128-150` almost literally, adding only a `symbol` field:
   `_validation_error`, `_provider_unreachable`, `_reauth_needed`,
   `_history_unavailable`.
2. **Live divergence:** `quotes.py:411-429` and `price_history.py:667-695`
   hand-roll the tool-boundary mapping (`except (ValueError, TypeError) →
   ToolError`), while `transactions.py:1298` and `options_chain.py:877`
   already use the shared helper `tool_errors.raise_classified_tool_error`,
   which also prefixes `reauth_needed:`/`provider_unreachable:`. A
   `ConnectivityError` or `ReauthorizationRequiredError` escaping in quotes
   or price_history today reaches the agent unclassified.

**Refactor proposed by report:** move envelopes to a shared module with an
optional `symbol: str | None = None` parameter; route the remaining two tool
wrappers through `raise_classified_tool_error`; TDD test that a
`ConnectivityError` raised inside `get_quotes`/`get_price_history` surfaces
with the classified prefix.

## Symptom

Two market-data tools (`get_quotes`, `get_price_history`) each carry a
private copy of the same result-envelope builders, and their MCP tool
wrappers classify only `(ValueError, TypeError)` at the boundary — unlike
`get_transaction_history_tool` and both option-chain wrappers, which catch
the auth taxonomy too and emit `reauth_needed:`/`provider_unreachable:`
prefixed `ToolError`s. Expected (per the convention established by bug
`domain-errors-swallowed`): one shared envelope implementation and a uniform
classified boundary in all five tool wrappers.

One precision on the report's strongest claim: through the **normal
plumbing**, a `ConnectivityError` does **not** escape `get_quotes` /
`get_price_history` — the domain functions catch it in their internal
`try` (quotes.py:347-363, price_history.py:563-596) and convert it to a
structured envelope (`{"outcome": "provider_unreachable" | "reauth_needed"}`),
which `docs/tools.md:767-768` and `docs/tools.md:959-960` document as the
*contractual* result shape for these two tools. The unclassified-escape gap
is real at the **boundary level**: any taxonomy error that does escape the
domain (raised outside the internal `try`, or by future code/refactoring)
passes the wrappers' `(ValueError, TypeError)` filter uncaught and surfaces
to the agent as the opaque `UnexpectedToolError`. The other three tool
wrappers have defense-in-depth against exactly this; these two do not.

## Reproduction

Duplication (static, verified by reading the code):

1. Read `src/schwab_mcp/quotes.py:128-150` — `_validation_error`,
   `_provider_unreachable`, `_reauth_needed` (no `symbol` field).
2. Read `src/schwab_mcp/price_history.py:147-181` — the same three helpers
   plus `_history_unavailable`, each identical except for a `symbol` field.

Boundary divergence (dynamic):

1. Monkeypatch `schwab_mcp.quotes.get_quotes` to raise
   `ConnectivityError(detail="Schwab API unreachable after retry")`
   (same technique as `tests/unit/test_tool_error_classification.py:90`).
2. Call `quotes.get_quotes_tool(None, "SPY")`.
3. Today: the exception escapes the wrapper (its `except (ValueError,
   TypeError)` does not match) and the MCP SDK wraps it into the opaque
   `UnexpectedToolError("Error executing tool get_quotes")` — no
   classification. The identical experiment on
   `transactions.get_transaction_history_tool` yields
   `ToolError("provider_unreachable: …")`.

Note: the report's suggested test wording — "a `ConnectivityError` raised
*inside* `get_quotes`" — must be pinned at the domain-function boundary, not
inside the domain's provider fetch: an error raised inside the real domain
`try` is caught and converted to an envelope (correct, contractual behavior,
not a failure).

## Suspected Code Paths

- `src/schwab_mcp/quotes.py:128-150` — three envelope helpers, module-private, no `symbol`.
- `src/schwab_mcp/price_history.py:147-181` — near-verbatim duplicate of the above plus `_history_unavailable`, each carrying `symbol`.
- `src/schwab_mcp/quotes.py:411-429` (`get_quotes_tool`) — hand-rolled boundary: `except (ValueError, TypeError) → ToolError(str(exc))`, no auth-taxonomy coverage.
- `src/schwab_mcp/price_history.py:667-695` (`get_price_history_tool`) — same hand-rolled pattern.
- `src/schwab_mcp/transactions.py:1289-1302` — already uses `raise_classified_tool_error` with `except (AuthError, InstrumentNotFoundError, ValueError, TypeError)`.
- `src/schwab_mcp/options_chain.py:877` and `:1134` — both wrappers already use `raise_classified_tool_error`.
- `src/schwab_mcp/tool_errors.py:21-41` — the shared helper; the natural home for the shared envelopes.
- `src/schwab_mcp/tokens.py:366-372` — `retry_call` wraps every provider failure into `ConnectivityError` with the original as `__cause__`; this is why the domains can classify reauth via `exc.__cause__` and why a direct `ReauthorizationRequiredError` does not escape through the normal path.
- `tests/unit/test_tool_error_classification.py:71-166` — pins the classified boundary for option-chain and transactions only; quotes and price_history are absent.

## Root Cause Hypothesis

The market-data tools (`quotes`, feature 010; `price_history`) predate
`tool_errors.py`, which was introduced by bug `domain-errors-swallowed` and
adopted only by the account/options tools. Their envelope builders and
boundary mapping were written in the earlier, module-local style and were
never converged when the shared helper landed, leaving one implementation of
the envelope knowledge per module (DRY violation) and two of the boundary
taxonomy (the classified prefix exists in only three of five wrappers).
Confidence: high — the duplication and the wrapper asymmetry are directly
verifiable in the source; only the historical ordering is inferred.

## Proposed Remediation

**Preferred**: Two coordinated moves, both behavior-preserving on the
contractual envelope path.

1. *Shared envelopes*: move the envelope builders into `tool_errors.py`
   (or a sibling `envelopes.py`) with an optional
   `symbol: str | None = None` parameter that omits the `symbol` key when
   `None` — `quotes` calls them without a symbol, `price_history` passes
   one — and delete both modules' private copies. The emitted dicts must
   remain byte-identical to today's (same keys, same order, no `symbol:
   null` on quotes envelopes) because contracts/mcp-tools.md §2-§3 and
   `docs/tools.md` pin these shapes.
2. *Classified boundary*: change both wrappers'
   `except (ValueError, TypeError)` to
   `except (AuthError, ValueError, TypeError)` routing through
   `raise_classified_tool_error`, mirroring `transactions.py:1301-1302`.
   This closes the defense-in-depth gap without touching the in-domain
   envelope conversion, which stays contractual (escaping taxonomy errors
   are the residual case the boundary must classify).

**Alternatives**:
- Boundary fix only (skip the envelope dedup): smaller diff, but leaves the
  DRY violation that is half the report — and the next envelope change gets
  made twice again.
- Convert quotes/price_history to the transactions pattern fully (taxonomy
  failures become `ToolError` prefixes instead of envelopes): rejected —
  contradicts the pinned contract for these two tools
  (`docs/tools.md:767-768`, `:959-960`) and changes the agent-visible
  result shape.

**Files likely to change**:
- `src/schwab_mcp/tool_errors.py` — shared envelope builders (+ docstring update).
- `src/schwab_mcp/quotes.py` — drop local helpers, import shared, wrapper except-clause.
- `src/schwab_mcp/price_history.py` — same.
- `tests/unit/test_tool_error_classification.py` — new wrapper coverage.
- `tests/unit/test_quotes_mapping.py`, `tests/unit/test_price_history_mapping.py` — envelope-shape parity against the shared builders (no assertion changes expected).
- `docs/tools.md` — only if the boundary note for the two tools needs the classified-prefix row added to their sections.

**Tests to add or update**:
- `TestQuotesToolClassifiedErrors` / `TestPriceHistoryToolClassifiedErrors`
  in `test_tool_error_classification.py`: monkeypatch the domain functions
  to raise `ConnectivityError` / `ReauthorizationRequiredError`; assert the
  exact `ToolError` type and the `provider_unreachable:` / `reauth_needed:`
  prefix (Red today — the errors escape unclassified).
- Envelope parity tests: shared builder with `symbol=None` produces exactly
  today's quotes dict; with a symbol produces exactly today's
  price_history dict (pins the no-`symbol: null` contract).
- Existing suite must stay green unchanged — the refactor is
  behavior-preserving on every currently reachable path.

## Risks & Considerations

- **Contract drift**: adding a `symbol` key unconditionally to quotes
  envelopes would violate the pinned contract §2/§3 — hence the
  omit-when-`None` parameter shape.
- **Import cycles**: `tool_errors.py` currently imports only from
  `schwab_mcp.errors`; envelope builders are plain dict constructors, so no
  new dependency risk — keep `ToolError` imports lazy as today.
- **Audit events**: the `auth_event` calls around envelope returns carry
  `detail` strings (`reauth_needed`, `provider_unreachable`, symbol
  selection); the refactor must not move or alter them
  (`test_quotes_events.py`, `test_price_history_events.py` pin these).
- **Observability**: no change to events; boundary classification only adds
  the prefix to a previously-opaque crash path.

## Open Questions

- [NEEDS CLARIFICATION: whether the shared envelopes should live in
  `tool_errors.py` or a new `envelopes.py` — `tool_errors.py` keeps one
  module for the error/taxonomy boundary; the report offers either.]
- None else; both claims are code-verifiable and the contracts are already
  documented in `docs/tools.md`.