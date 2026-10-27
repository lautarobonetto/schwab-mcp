# Research: Account Transaction History (006)

Date: 2026-10-23. Primary source: source code of the installed SDK
(`schwabdev==4.0.0`, read in `.venv/.../schwabdev/{client,validation}.py`),
schwab-py docs (independent reference SDK) and third-party operational
evidence (regress#125). Each decision cites its evidence.

## R1. Upstream endpoint and limits

**Decision**: use `GET /trader/v1/accounts/{accountHash}/transactions`
via `schwabdev.Client.transactions(accountHash, startDate, endDate,
types, symbol)`.

**Rationale**: signature verified against the installed SDK. Limits
documented in the SDK docstring: **max 3000 transactions per call;
date range max 1 year** — consistent with the 1-year window decided in
clarify Q1 (FR-004). `startDate`/`endDate` go in ISO-8601 (the SDK
converts them with `TimeFormat.ISO_8601`). `symbol` is optional and
filters upstream. Note: the schwab-py docs mention "60 days" for
`start_date`, but that is its `get_orders` documentation carried over;
the installed SDK docstring (source of truth for this repo) says 1
year. The quickstart includes a live verification of the window.

**Alternatives considered**: an `account_orders_all`-style endpoint for
all accounts — **does not exist** for transactions (the SDK only has
per-account `transactions`); therefore the orchestration iterates
`linked_accounts()` (the same way `positions.py` does with
`account_details_all`, which does not apply here).

## R2. `types` format and SDK validator bypass

**Decision**: 1 upcall per account with `types` = the full list of the
15 documented types, **comma-separated**:
`"TRADE,RECEIVE_AND_DELIVER,DIVIDEND_OR_INTEREST,ACH_RECEIPT,ACH_DISBURSEMENT,CASH_RECEIPT,CASH_DISBURSEMENT,ELECTRONIC_FUND,WIRE_OUT,WIRE_IN,JOURNAL,MEMORANDUM,MARGIN_CALL,MONEY_MARKET,SMA_ADJUSTMENT"`.
For this single call the SDK parameter validator is disabled in a
**scoped and reversible** way (toggle of `client._validator.enabled`
inside a helper of `transactions.py`, restored in `finally`).

**Rationale**: (a) the SDK validator (`validation.py:_v_transactions`)
uses `_vin`, which requires `types` to be **a single value** of the set —
it would reject the comma-separated list; (b) the upstream format
**does** accept comma-separated types: it is the documented format sent
by the two reference libraries (schwab-py sends
`','.join(transaction_types)`) and the regress#125 research verified it
against both ("Comma-separated is the documented working format"); (c)
the alternative of 1 upcall per type would be 15 sequential calls per
account (~3–7 s per account) — violates the SC-001 budget of ≤ 5 s p95
and multiplies the rate-limiting surface; (d) the SDK is pinned
(`schwabdev==4.0.0`), so the private attribute touched is under version
control; the helper centralizes the bypass with a comment and its own
test.

**Alternatives considered**:
- *1 upcall per type per account*: deterministic with the validator
  active, but unacceptable latency (see (c)) and more load on the
  provider.
- *Repeated `params`* (`types=TRADE&types=...`): would require calling
  `client._request` (even more private than the toggle) and regress#125
  ruled out that it changes the result.
- *`validate_params=False` when building the client*: disables
  validation for **all** calls (positions, quotes, etc.) — an
  unjustified loss of security for the rest of the app.

## R3. Upstream cap of 3000 transactions (completeness)

**Decision**: if a per-account response returns exactly 3000 movements
(upstream cap), the tool **splits the range by bisection** and
re-queries each half recursively (same type list), merging and
deduplicating by `(account_hash, activityId)`; bounded depth (the
minimum sub-range is 1 day). There is no upstream pagination, so the
split is the only path to guaranteed completeness (SC-004).

**Rationale**: FR-006/SC-004 forbid silent truncation; the 3000 cap is
real (SDK docstring). Bisection converges: a 1-year range with >3000
movements requires few iterations for personal accounts; the extra
cost is paid only when there really are >3000 movements in the
sub-range.

**Alternatives considered**:
- *Report the truncation and let the agent subdivide*: satisfies the
  "no silence" rule but degrades SC-005 (the agent would have to guess
  how to split).
- *Fixed monthly split always*: would multiply upcalls ×12 per account
  on every query — violates latency/budget without need.

## R4. Date semantics and timezone

**Decision**: dates (`YYYY-MM-DD`) are interpreted in the account's
market timezone (**America/New_York**, clarify Q2), inclusive
boundaries: `startDate` = `T00:00:00-05:00/-04:00` (the day's actual
offset via `zoneinfo`), `endDate` = `T23:59:59` of the end day (sent
as the inclusive final instant in ISO-8601). A future `end_date` is
rejected in validation (spec edge case).

**Rationale**: matches the market's operating calendar and how the
owner reads their account statements; `zoneinfo` is stdlib (Principle
III). The same range requested twice yields the same set (determinism
required by the spec).

## R5. Category normalization (closed enum) and spec alignment

**Decision**: provider→normalized category mapping:

| Upstream type | Category |
|---------------|-----------|
| `TRADE` | `trade` |
| `RECEIVE_AND_DELIVER` | `transfer` |
| `ACH_RECEIPT` / `ACH_DISBURSEMENT` / `CASH_RECEIPT` / `CASH_DISBURSEMENT` / `ELECTRONIC_FUND` / `WIRE_IN` / `WIRE_OUT` | `transfer` |
| `DIVIDEND_OR_INTEREST` | `dividend_or_interest` |
| `JOURNAL` | `adjustment` |
| `SMA_ADJUSTMENT` | `adjustment` |
| `MEMORANDUM` / `MARGIN_CALL` / `MONEY_MARKET` | `other` |

The category enum is **extended with `dividend_or_interest`** compared
to the one decided in clarify Q3 (which listed `interest` and
`dividend` as separate values): the provider reports dividends and
interest as a single `DIVIDEND_OR_INTEREST` type and there is no
discriminating field in the payload, so the faithful projection (spec:
"faithful projection") is a combined category. The values `interest`,
`dividend`, `fee` and `corporate_action` remain **reserved** in the
enum (no mapping in v1). The provider's original text (full `type` +
`description`) goes only in the extended detail (FR-007, clarify Q3).
The spec (FR-002) is updated with the added value.

**Rationale**: classifying dividends vs. interest by a description
heuristic would be fuzzy matching, explicitly rejected in the spec's
Assumptions; inventing a category is not possible without inventing
data.

**Alternatives considered**: map `DIVIDEND_OR_INTEREST → other`
(faithful but degrades value for the agent); heuristic over
`description` (violates "no fuzzy matching").

## R6. Instrument filter validation

**Decision**: when `symbol` is present, the tool makes **1 upcall**
`instruments(symbols=[symbol], projection="symbol-search")`. (Correction
2026-10-23, found in live testing: the SDK validator rejects
`SYMBOL_SEARCH`; valid projections are lowercase.) If the symbol does
not exist → explicit error `instrument_not_found` (FR-009c, spec edge
case: distinguish "unknown instrument" from "no movements"). If it
exists, the filter travels upstream (`symbol=`) and an empty result
genuinely means "no movements for that instrument in the range"
(`detail: no_movements_for_instrument`).

**Rationale**: the upstream endpoint does not distinguish "bad symbol"
from "no results"; without the validation, SC-005 (unambiguous
decision) is impossible to meet. The cost is 1 extra upcall only when
there is a filter.

## R7. MCP-side pagination

**Decision**: stateless pagination: the tool sorts the merged history
by `occurred_at` ascending (tie-break: `account_hash`, `activityId`),
delivers pages of **50 movements** (clarify Q4) starting at `offset`
(default 0), and reports `total_count`, `returned`, `has_more` and
`next_offset` when `has_more=true`. The agent repeats the same query
with the `next_offset` to continue.

**Rationale**: upstream has no pagination (it delivers everything ≤
cap, handled in D3), so pagination is a deterministic MCP-side slice;
offset over a sorted list is trivial to test (SC-006: zero duplicates,
zero gaps). Caveat documented in the contract: if the agent is slow
between pages and new movements arrive, the offset may shift —
paginate soon; the tool is stateless and promises no cross-page
consistency.

**Alternatives considered**: continuation token with signature/state →
unjustified complexity (KISS); cursor by the last movement's date →
ambiguous with identical dates.

## R8. Operational risk: `200 OK + []` without read permission

**Decision**: the tool **does not invent errors** on an empty result:
it returns `outcome: ok, detail: no_movements, total_count: 0` (a
faithful projection of upstream). The known risk — the endpoint may
return `200 + []` when the app/account lacks transaction read
permission (app tier without Trading Production, or account without
thinkorswim enabled; evidence regress#125) — is mitigated with
**documentation** in `docs/tools.md` and `quickstart.md`: if the range
is wide and the account has activity visible on schwab.com but the
tool persistently returns empty, the likely cause is app/account
permission, not data.

**Rationale**: from the response a genuine empty is indistinguishable
from a permission-caused empty (regress#125 documented that every
filter form returns `200 + []`); fabricating an error would be a false
positive for genuinely empty accounts (KISS + fidelity). The doc gives
the agent the diagnostic signal.

## R9. Reuse of existing vocabulary and channels

**Decision**: `TransactionsResult` replicates the `PositionsResult`
pattern (feature 003): `outcome ∈ {ok, partial_failure,
transient_failure, reauth_required}`, `retryable` (true only for
transient), closed-enum `detail`, `accounts_failed` only in partial,
`retrieved_at` ISO-8601 UTC. Authentication errors via the `errors.py`
taxonomy; upcalls under `tokens.retry_call` (1 attempt: no internal
retries, FR-010); audit via `log.auth_event` + redaction filter
(FR-011). Tool registration in `server.py` with `MCPServer.add_tool` +
`structured_output` (pattern of 003/005).

**Rationale**: a single outcome vocabulary across the whole MCP (DRY);
agents already know the decision playbook of `docs/tools.md`.

## R10. Currency

**Decision**: `currency` per movement; upstream does not expose a
per-transaction currency field and the project's brokerage accounts are
USD-denominated → default `"USD"` documented in the data model. No
conversion (spec Assumptions).

**Alternatives considered**: omit currency (violates FR-005); infer by
instrument (fuzzy, rejected).