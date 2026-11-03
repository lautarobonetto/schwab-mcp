# Bug Assessment: `$SPX` + `delta_target` fails — schwabdev default 10 s timeout vs SPX-sized chain fetches

- **Slug**: spx-delta-timeout
- **Created**: 2026-11-03
- **Source**: pasted text (live-run bug report, v0.9.2, commit ee66bd8)
- **Verdict**: valid
- **Severity**: high

## Report (verbatim or summarized)

Pasted report from a live stdio-MCP run (2026-11-03, 14:13–14:40 CT). **Bug 1** (primary, in scope
for this assessment): `get_option_chain` on `$SPX` with `delta_target` fails deterministically
(4/4 live attempts) while the same call without `delta_target`, and `delta_target` on SPY/`$XSP`,
succeeds. Root cause claimed: `schwabdev.Client` is instantiated without a `timeout` parameter, so
the provider library's default 10 s read timeout applies; the `delta_target` path fetches with
`strikeCount = max(max_strikes, 100)` and re-fetches at 200 when the target is not bracketed, and a
full `$SPX` chain at `strikeCount=200` exceeds 10 s at Schwab's API → `requests` timeout →
`ConnectivityError("Schwab API unreachable after retry")`.

Out-of-scope findings noted by the same report (brief, deferred): Bug 2 — domain errors are wrapped
by FastMCP so callers only see "Error executing tool …"; Issue 3 — a requested `expiration_date`
with DTE > 60 is silently omitted with `outcome:"ok"`; Issue 4 — undocumented third
`settlement_type` value `A` in provider data.

## Symptom

`get_option_chain {"symbol":"$SPX", "expiration_date":"2026-12-18", "delta_target":-0.35}` returns
`isError: true` (surface message: "Error executing tool get_option_chain"; stderr shows
`requests` read timeout after 10 s mapped to `ConnectivityError`). Expected: a centered chain result
like the equity/ETF paths produce. The failure is specific to the combination `$SPX` +
`delta_target` — huge chain + enlarged `strikeCount` fetch.

## Reproduction

1. Serve the MCP gateway (`uv run schwab-mcp serve`) and connect via stdio (`initialize` →
   `tools/call`), or reproduce directly against the local checkout.
2. Call `get_option_chain` with `{"symbol":"$SPX","expiration_date":"2026-12-18","delta_target":-0.35}`.
3. Observe `isError: true` with no domain detail in the MCP response; the serve stderr shows
   `requests.exceptions.ReadTimeout` / `ConnectionError` on
   `/marketdata/v1/chains?symbol=%24SPX&...&strikeCount=200...`, then
   `schwab_mcp.errors.ConnectivityError`.

Reported as deterministic (4/4 live attempts). Counter-cases from the report: no `delta_target` on
`$SPX` → OK; `delta_target` on SPY and `$XSP` → OK. [NEEDS CLARIFICATION: whether the first
attempt at `strikeCount = max(max_strikes, 100)` alone already exceeds the 10 s timeout for `$SPX`,
or only the ceiling-200 re-fetch does — both are plausible for a full SPX chain.]

## Suspected Code Paths

- `src/schwab_mcp/server.py:94-101` — `schwabdev.Client(config.app_key, …, tokens_db=store_path,
  call_on_auth=guard_hook, open_browser_for_auth=False)` passes **no `timeout` argument**. Verified
  against the installed library: `schwabdev.Client.__init__(…, timeout: int = 10, …)` — the default
  10 s read timeout applies to every provider request made through this client.
- `src/schwab_mcp/options_chain.py:744-755` — with `delta_target`, the fetch runs at
  `strike_count=max(query.max_strikes, DELTA_STRIKE_COUNT_FLOOR=100)` and, when the target is not
  bracketed, one re-fetch at `DELTA_STRIKE_COUNT_CEILING=200`. Confirmed in source; matches the
  observed `strikeCount=200` request URL.
- `src/schwab_mcp/options_chain.py:296-305` (`fetch_option_chain`) — the provider call is wrapped in
  `retry_call(client.option_chains, 0, …)`, i.e. **retries=0**: one attempt, then
  `ConnectivityError`.
- `src/schwab_mcp/tokens.py:332-377` (`retry_call`) — catches any `Exception`, and when attempts are
  exhausted raises `ConnectivityError("Schwab API unreachable after retry; stored tokens were not
  modified")` from the original exception. Confirmed as the error the caller sees.
- `src/schwab_mcp/cli.py:150` and `src/schwab_mcp/cli.py:330` — two additional `schwabdev.Client(…)`
  instantiations (auth flow, `renew`), also without `timeout`.
- `src/schwab_mcp/config.py` — `Config` dataclass loaded from environment variables; currently has
  **no** request-timeout setting, so there is no way for an operator to raise the provider timeout.

## Root Cause Hypothesis

The provider client uses schwabdev's default `timeout=10` (seconds) because none of the three
`schwabdev.Client` call sites pass a `timeout` argument. The `delta_target` path deliberately
enlarges `strikeCount` (100, up to 200 on re-fetch) to bracket the target delta; for `$SPX` — whose
full chain is by far the largest in the ecosystem — such a fetch takes longer than 10 s at Schwab's
API, so `requests` raises a read timeout, which `retry_call` converts into
`ConnectivityError`. Equity/ETF and `$XSP` chains complete well under 10 s (the report's 17
non-delta chain calls took 1.6–2.4 s), which is why only the SPX-sized + delta path fails.
Confidence: **high** — the missing `timeout` argument, the library's `timeout: int = 10` default,
the `strikeCount` expansion, and the live deterministic failure all line up.

One correction to the report: it claims "`retry_call` retries the same doomed request (another
~10 s)". In `fetch_option_chain` the wrap uses `retries=0`, so there is **no** second HTTP attempt;
the "after retry" wording in the `ConnectivityError` message is simply inaccurate for this path.
Any observed extra latency more likely comes from urllib3/`requests` internal connection retries
(the traceback's "Max retries exceeded"), not from `retry_call`. Confidence: high (direct source
read).

## Proposed Remediation

**Preferred**: make the provider request timeout explicit and configurable, and raise the default.
Concretely:

1. Add a `request_timeout` field to `Config` (env var, e.g. `SCHWAB_MCP_REQUEST_TIMEOUT`, seconds,
   validated positive integer; default **60** — generous headroom over the worst observed SPX fetch,
   matching the constitution's "simplest thing that works" while keeping giant chains viable).
2. Centralize client construction in one factory (DRY — there are currently three near-identical
   `schwabdev.Client(…)` call sites) and pass `timeout=config.request_timeout` there. Update
   `server.py:94`, `cli.py:150`, `cli.py:330` to use it.
3. As a defensive complement, keep the `strikeCount` expansion as is — no cap for index symbols in
   the preferred fix, since a correct 60 s timeout makes the ceiling fetch viable and capping would
   degrade delta centering quality on exactly the flagship symbol.

**Alternatives** (optional):
- Hard-code `timeout=30` at the three call sites without config plumbing. Smallest diff, but
  operators cannot adapt to slow links; contradicts the configurability the report suggests.
- Retry timeouts with a longer second-attempt timeout, or skip retrying on `requests.Timeout`.
  Moot at the `fetch_option_chain` level today (`retries=0`) and adds complexity for no measured
  benefit; the retry-on-any-exception behavior in `retry_call` remains a separate design question.
- Cap `strike_count` for index symbols (detect `$`-prefixed symbols). Protects the timeout but
  silently shrinks the bracketing window for SPX delta targets — worse product behavior for the
  same symbol the feature exists for.

**Files likely to change**:
- `src/schwab_mcp/config.py` — add `request_timeout` field + env parsing + validation.
- `src/schwab_mcp/server.py`, `src/schwab_mcp/cli.py` — client construction (ideally via a shared
  factory, e.g. in a small helper module or `config.py`-adjacent location).
- `tests/unit/test_config.py` (or equivalent) and the client-construction unit tests.

**Tests to add or update** (TDD — regression first, per the constitution):
- Unit: `Config` parses and validates `request_timeout` from the environment (default 60; rejects
  zero/negative/non-integer with the existing validation-error style).
- Unit/regression: client construction passes `timeout` through — assert the
  `schwabdev.Client(…)` call (stubbed in the existing test fakes) received
  `timeout=config.request_timeout` in all three code paths (serve, auth, renew).
- Unit: `fetch_option_chain` with a fake client whose `option_chains` sleeps past a small timeout
  surfaces `ConnectivityError` (keeps locking the error-mapping contract; optionally asserts a
  single provider attempt, documenting the `retries=0` behavior).

## Risks & Considerations

- **Behavioral**: raising the timeout means genuinely hung provider calls now take up to 60 s
  before erroring — MCP clients must tolerate the longer latency; acceptable for a data-fetch tool.
- **Contract/config surface**: a new env var is a documented interface change — update
  `docs/usage.md` / `docs/installation.md` and the affected spec contract in the same commit
  (constitution gate).
- **DRY risk**: fixing the timeout only in `server.py` leaves the auth/renew clients at 10 s;
  the shared factory removes the triplication and prevents recurrence.
- **Observability**: the "after retry" wording in `ConnectivityError` is misleading for
  `retries=0` call sites; worth a wording check when touching `retry_call`'s neighborhood
  (optional, not required for this fix).
- **Performance budgets**: no change to hot paths beyond the timeout constant; no new allocations.

## Open Questions

- [NEEDS CLARIFICATION: measured duration of the `strikeCount=100` vs `strikeCount=200` SPX fetch —
  determines whether the floor fetch alone already exceeds 10 s (affects how aggressive the default
  timeout must be).]
- [NEEDS CLARIFICATION: should the timeout also cover the `option_expiration_chain` and quote paths
  uniformly via the shared client, or is a per-call timeout override ever warranted? Preferred fix
  assumes uniform client-level timeout.]