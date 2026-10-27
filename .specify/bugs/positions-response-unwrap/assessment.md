# Bug Assessment: get_open_positions fails live — Response not unwrapped and invented payload shape

- **Slug**: positions-response-unwrap
- **Created**: 2026-10-24
- **Source**: pasted text (context from the live validation session of feature 006)
- **Verdict**: valid
- **Severity**: critical

## Report (verbatim or summarized)

Original report (pasted text):

> "The same Response fix for get_open_positions (feature 003), which
> also requires cross-referencing accountNumber↔hashValue — let me know
> when you want to tackle it."

Context verified in this same session (2026-10-23/24, live test):

- Tool call through the connected MCP channel:
  `tools.schwab.get_open_positions({})` →
  `Error: Error executing tool get_open_positions` (generic SDK/MCP
  error; the real exception only shows in the server log).
- Verified with the real SDK (`schwabdev==4.0.0`):
  `Client.account_details_all(fields="positions")` returns a
  `requests.Response` (`<Response [200]>`), not a dict.
- Real payload (`status 200`, inspected by keys, without values):
  a JSON list at the top level:
  `[{"aggregatedBalance": {...}, "securitiesAccount": {"accountNumber",
  "positions": [...], "currentBalances", ...}}]`.
- `positions.py` expects a dict with the key `accountDetails` — which
  does not exist in the real payload.

## Symptom

`get_open_positions` fails with a generic error on **every** live
invocation against the real Schwab API (the test suite passes because the
fakes return already-parsed dicts with the `{"accountDetails": [...]}` shape
the code assumes). Expected: a `PositionsResult` with `outcome=ok` and the
positions of all linked accounts.

## Reproduction

1. With valid credentials (`uv run schwab-mcp auth-status` → `state: valid`),
   start `uv run schwab-mcp serve` (with the `SCHWAB_CALLBACK_URL` already
   normalized — see the fixed `config-callback` bug).
2. Invoke the `get_open_positions` tool through any MCP stdio client.
3. Observe: generic error "Error executing tool get_open_positions";
   on the server's stderr: `AttributeError: 'Response' object has no
   attribute 'get'` (and, if only the unwrap were fixed, the mapping would
   then fail on the payload shape: `payload.get("accountDetails")` over a
   list).

Deterministic alternative without network (in-process):

```python
import schwabdev
from schwab_mcp.config import load_config
from schwab_mcp.positions import get_open_positions
cfg = load_config()
client = schwabdev.Client(cfg.app_key, cfg.app_secret, cfg.callback_url,
                          tokens_db=cfg.token_db, open_browser_for_auth=False)
get_open_positions(client)   # AttributeError: 'Response' object has no attribute 'get'
```

## Suspected Code Paths

- `src/schwab_mcp/positions.py:388` — `payload = client.account_details_all(fields="positions")`:
  uses the SDK `Response` directly as if it were a dict (no
  `.json()` nor HTTP status classification). This is the same defect fixed
  for 006 in `transactions.py` via `schwab_mcp.provider.response_json()`.
- `src/schwab_mcp/positions.py:430-459` — `_detect_account_failures(payload)`,
  `_extract_successful_accounts(payload)` and `_transform_provider_payload(payload)`
  read `provider_payload.get("accountDetails", [])`: a payload shape the
  real endpoint does not return (real: top-level list with
  `securitiesAccount` per element).
- `src/schwab_mcp/positions.py:175-177` — `_hash_account(account_number)`:
  local truncated SHA-256 hash of the account number. It is not the
  provider's opaque identifier (`hashValue` from `linked_accounts()`), so the
  `account_hash` values of `get_open_positions` are not consistent with those
  of `get_transaction_history` (FR-008 of 006 requires account coverage
  consistency). Moreover, a SHA-256 truncated to 8 hex of a short account
  number is brute-forceable — the correct and safe identifier is the
  provider's `hashValue`.
- `tests/unit/test_positions.py:49-60` — `FakePositionsClient` returns
  dicts with the assumed shape: the tests pin the wrong contract, which is
  why the suite is green despite the live bug.

## Root Cause Hypothesis

Feature 003 was built (and tested) against a presumed payload shape
(`{"accountDetails": [{"accountNumber", "positions"}]}` with already-parsed
responses) that does not match the real contract of the SDK or of the
`GET /trader/v1/accounts?fields=positions` endpoint (which returns a
`requests.Response` with a list of `{aggregatedBalance, securitiesAccount}`
and does not expose the account hash — you must cross-reference
`securitiesAccount.accountNumber` with the `hashValue` from
`linked_accounts()`). Confidence: **high** — reproduced live and confirmed
by inspecting the installed SDK and the real payload.

## Proposed Remediation

**Preferred**: align `positions.py` with the already-proven pattern of
`transactions.py` (feature 006):

1. **Unwrap** (reuse, zero new code): `payload = response_json(...)` from
   `src/schwab_mcp/provider.py` for `account_details_all()` and for the
   new `linked_accounts()` upcall; errors 401/403 → `reauth_required`,
   5xx/408/429 → `transient_failure` (classification already centralized).
2. **Shape adaptation**: new normalizer (pure, testable) that converts the
   real list
   `[{"aggregatedBalance", "securitiesAccount": {...}}]` into the internal
   format `{"accounts": [{"accountHash", "positions": [...]}]}` already
   consumed by `map_provider_positions`. The sub-mapping of position fields
   (`longQuantity`, `averagePrice`, `marketValue`, `instrument.symbol`,
   `assetType`, …) matches the real keys observed, so the
   mapping core does not change.
3. **accountNumber↔hashValue cross-reference**: obtain
   `response_json(client.linked_accounts())` → map
   `{accountNumber: hashValue}`; the normalizer resolves the real hash by
   `accountNumber` (the elements of `account_details_all` do not carry
   `hashValue`). Account with no match in the cross-reference →
   `partial_failure` with `accounts_failed` (never an invented hash).
4. **Retire the local hash**: remove `_hash_account` (or keep it only if
   some test requires it — preferably remove it) and use the provider's
   `hashValue` in `accounts_failed` too.
5. `server.py` requires no changes (the tool is already registered; there
   are no inputs to validate).

**Alternatives** (optional):

- Minimal change: only unwrap with `.json()` and see what MappingError
  comes next. Rejected: it ships a tool broken in a different way (empty
  results/garbage) and repeats the anti-pattern of testing against fake
  noodles.
- Use `GET /accounts/{hash}?fields=positions` per account (as 006 does
  with `transactions`): brings the hash by construction and real per-account
  errors, at the cost of 1 upcall per account (the bulk
  `account_details_all` is 1 call total). Rejected for now: more upcalls
  and a rewrite of the orchestration; bulk + cross-reference complies with
  1 fixed extra upcall.

**Files likely to change**:

- `src/schwab_mcp/positions.py` (unwrap, shape normalizer, hash
  cross-reference, removal of `_hash_account`)
- `tests/unit/test_positions.py` (fakes returning `requests.Response`
  with the real shape + reauth/transient/partial cases)
- `tests/unit/test_no_secrets_in_output.py` (ensure no field carries the
  real `accountNumber` — only `hashValue`)
- `docs/tools.md` + `docs/CHANGELOG.md` (documentation up to date)
- `specs/003-list-open-positions/` — correction note for the assumed
  data-model (similar to what was done in research.md of 006)

**Tests to add or update**:

- Regression test (Red first, constitution I): fake whose
  `account_details_all()` returns a real `requests.Response` with the real
  list → `outcome=ok`, positions mapped, `account_hash == hashValue`.
- 401/403 → `reauth_required`; 500 → `transient_failure` with
  `retryable=true`; malformed JSON → `transient_failure`.
- `accountNumber` with no match in `linked_accounts()` → `partial_failure`
  with `accounts_failed` (no local hash).
- Per-account `error` (if `_detect_account_failures` is kept): define what
  triggers that path with the real shape or mark it obsolete.
- No-secrets: `accountNumber` never appears in the output.

## Risks & Considerations

- **Visible identifier changes**: the tool's `account_hash` values change
  from "sha256[:8] of the number" to the real `hashValue` — breaking for
  any agent that cached hashes from `get_open_positions`;
  in exchange, they become consistent with `get_transaction_history` (and
  with the rest of the ecosystem). Record in the CHANGELOG.
- **Additional upcall**: `linked_accounts()` adds 1 call per query
  (2 total); minimal impact on the 5 s p95 budget, measure in the
  existing performance test.
- **Order/duplicates of the cross-reference**: if `linked_accounts()` and
  `account_details_all()` differ in order or content (new account between
  the two calls), match by `accountNumber` and fail explicitly on what is
  not matched — never assume by index.
- **Credential safety**: removing the local hash reduces the attack
  surface (a truncated SHA-256 of short account numbers is reversible by
  brute force).
- **Observability**: the `positions_query_*` events do not change; the
  partial_failure path keeps the vocabulary of the 003 contract.

## Open Questions

- [NEEDS CLARIFICATION: does the bulk endpoint always return accounts in
  the same order as `linked_accounts()`? The plan matches by
  `accountNumber`, so order should not matter — validate with the real
  single-account app (already observed: consistent order with 1
  account).]
- [NEEDS CLARIFICATION: are there multi-type accounts (margin/cash) that
  appear twice in `account_details_all`? If so, define dedup by
  `accountNumber` for the cross-reference.]