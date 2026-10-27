# Bug Fix: get_open_positions fails live — Response not unwrapped and invented payload shape

- **Slug**: positions-response-unwrap
- **Fixed**: 2026-10-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

`get_open_positions` (feature 003) now works against the real API:
unwrapping of `requests.Response` via `schwab_mcp.provider.response_json`
(reuse of the feature 006 mechanism), normalization of the real payload
shape (top-level list of `{aggregatedBalance, securitiesAccount}`),
account identifier = provider `hashValue` cross-referenced by
`accountNumber` with `linked_accounts()` (removal of the local truncated
SHA-256 hash), and derivation of option `strike_price`/`expiration_date`
from the OCC symbol.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/positions.py` | modified | Unwrap of `linked_accounts()` + `account_details_all()` with `response_json`; new `_normalize_positions_payload()` (accepts the real and legacy shapes); new `_parse_occ_option_symbol()`; matched/unmatched partition → explicit `partial_failure`; removal of `_hash_account` and of the `hashlib` import; `_transform_provider_payload`/`_detect_account_failures` use the resolved `accountHash` |
| `tests/unit/test_positions_live_response.py` | new | 7 regression tests with fakes returning real `requests.Response` objects (real payload shape) |
| `tests/unit/helpers.py` | new | Shared helper `build_response()` (single source of truth for building `Response` in tests) |
| `tests/unit/test_server_tool.py` | modified | `FakePositionsClient` adds `linked_accounts()` with opaque hashes derived from its payload |
| `tests/performance/test_positions_budgets.py` | modified | The fake adds `linked_accounts()` (new upcall of the orchestration) |
| `docs/tools.md` | modified | Note: `account_hash` = provider `hashValue`, consistent across tools |
| `docs/CHANGELOG.md` | modified | `Fixed` entry with the detail and the breaking change of `account_hash` |
| `specs/003-list-open-positions/research.md` | modified | Post-implementation correction note (real payload shape, `hashValue`, OCC) |

## Diff Highlights (optional)

Orchestration (before → after):

```python
# before: Response used as a dict, local hash of the account number
payload = client.account_details_all(fields="positions")
account_hash = _hash_account(account_number)  # sha256[:8]

# after: unwrap + accountNumber↔hashValue cross-reference
listing = response_json(client.linked_accounts())
raw = response_json(client.account_details_all(fields="positions"))
hash_by_number = {a["accountNumber"]: a["hashValue"] for a in listing}
provider_payload = _normalize_positions_payload(raw, hash_by_number)
# accounts with no resolvable hash → accounts_failed (never an invented hash)
```

Options with OCC symbol (before → after):

```python
# before: instrument.get("strikePrice", 0.0) → real 0.0 → ValidationError (gt=0)
# after: derivation from the OCC
strike, parsed_expiry = _parse_occ_option_symbol(instrument.get("symbol", ""))
# "AMD   261120P00090000" → strike 630.0, expiry 2026-11-20
```

## Tests Added or Updated

- `tests/unit/test_positions_live_response.py::TestLiveSdkResponses::test_ok_from_real_shape_responses` — the real SDK shape produces `ok` with mapped positions
- `...::test_account_hash_is_provider_hash_value` — `account_hash` = provider `hashValue` (cross-referenced by `accountNumber`), not a local hash
- `...::test_http_401_maps_to_reauth_required` — HTTP 401 → `reauth_required/reauth_needed`
- `...::test_http_500_maps_to_transient_failure` — HTTP 500 → `transient_failure` with `retryable=true`
- `...::test_unmatched_account_number_is_partial_failure` — account with no resolvable hash → `partial_failure` with `accounts_failed` (no silent drop, no local hash)
- `...::test_raw_account_number_never_in_output` — the raw account number never appears in the output (credential safety)
- `...::test_option_strike_and_expiry_parsed_from_occ_symbol` — strike/expiry derived from the OCC symbol when the instrument does not carry them

## Local Verification

- Commands: `uv run pytest -q` → **758 passed, 0 skipped** (full suite)
- Manual (live, real SDK `schwabdev==4.0.0` with valid credentials):
  `get_open_positions(client)` → `outcome=ok`, `detail=data_received`,
  8 positions (AMD/SPCX/MSFT/XSP options + strikes 630/620/155/165/525
  parsed from the OCC), `account_hash` = real provider `hashValue`.

## Deviations from Assessment

1. **Cross-reference by `accountNumber`, not by order**: the assessment
   already considered the cross-reference; the implementation matches by
   `accountNumber` (not by index) and reports accounts with no match as
   `partial_failure` with synthetic `unmatched-account-N` labels (the
   model requires a non-empty `account_hash` and the raw number cannot be
   emitted).
2. **`_detect_account_failures` kept**: the per-account error mechanism
   (`"error"` in the entry) does not exist in the real bulk endpoint
   payload; it is kept operating on the normalized shape for compatibility
   with the 003 contract and existing fakes.
3. **New discovery (outside the assessment)**: real OPTION instruments do
   not carry `strikePrice`/`expirationDate` — on top of the unwrap fix,
   `_parse_occ_option_symbol()` was added (derivation from the OCC
   symbol). Without it, the tool crashed live with
   `ValidationError: strike_price Input should be greater than 0`.
4. **`server.py` unchanged**: confirmed — the already-registered tool
   requires no additional wrapper (no inputs to validate).

## Follow-ups

- Reload the connected MCP server and re-verify `get_open_positions`
  through the real channel (the in-flight process still runs the old
  code).
- `/speckit.bug.test slug=positions-response-unwrap` for formal post-fix
  verification.
- Consider documenting in `docs/usage.md` that the `account_hash` values
  in `get_open_positions` output changed (breaking for consumers that
  cached them) — already recorded in the CHANGELOG.