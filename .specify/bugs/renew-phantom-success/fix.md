# Bug Fix: phantom `renewal_success` on revoked tokens (unchecked HTTP status)

- **Slug**: renew-phantom-success
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

The tie-breaker probe and the `serve` startup validation now classify the
HTTP status of `linked_accounts()` through the shared
`provider.response_json` unwrapper instead of treating "did not raise" as
success, so a server-side-revoked refresh token yields
`reauth_required` (exit 3/4) instead of a phantom `renewed` (exit 0). A
probe-derived `renewed` outcome is additionally verified against the
store, `auth` now warns that completing an authorization revokes other
installations sharing the app key, and the one-token-set rule is
documented.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/renewal.py` | modified | `_tie_breaker_probe` routes `linked_accounts()` through `provider.response_json` (401/403 → `reauth_required`/`refresh_rejected`; 5xx/408/429/malformed → `transient_failure`/`provider_unreachable`, retryable; catch-all → `reauth_required`). Added store-consistency guard: probe 2xx with a stale/unreadable store → `reauth_required` with new detail `renewal_unverified` (nothing was written, so no renewal to claim). Added `renewal_unverified` to `_VALID_DETAILS`. `_do_renew` now passes `store_path` to the probe and maps `transient_failure` probe outcomes to the `connectivity` terminal event. |
| `src/schwab_mcp/server.py` | modified | Startup validation (step 4): the `retry_call(client.linked_accounts, retries=1)` result is classified via `response_json` before `renewal_success` is emitted; 401/403 → `renewal_failure outcome=reauth_required` + raise (exit 4), 5xx/malformed → `renewal_failure outcome=connectivity` + raise (exit 7). |
| `src/schwab_mcp/cli.py` | modified | Issue 2: after a successful `auth`, stderr note + `auth_success` event detail now state that other installations sharing the same app key have had their token sets revoked. |
| `docs/usage.md` | modified | Token lifecycle: documented the one-active-token-set-per-app-key behavior (concurrent installations revoke each other) and the store-lifetime-only limitation of `auth-status`. |
| `docs/tools.md` | modified | `renew` result schema: added `renewal_unverified` to the `detail` closed enum and to the `reauth_required` semantics (with its meaning for agents). |
| `docs/CHANGELOG.md` | modified | `[Unreleased]` section: Fixed + Changed entries for this bug. |
| `specs/002-automated-token-renewal/contracts/cli.md` | modified | `reauth_required` detail row extended with `renewal_unverified` (closed-enum contract updated in the same change, per the assessment's Risks section). |
| `tests/unit/test_renewal.py` | modified + added tests | See below. |
| `tests/integration/test_failures.py` | added tests | See below. |
| `tests/integration/test_auth.py` | added test | See below. |

## Diff Highlights

Probe classification (`src/schwab_mcp/renewal.py`, `_tie_breaker_probe`):

```python
try:
    response_json(client.linked_accounts())
except ReauthorizationRequiredError:
    return RenewalOutcome(outcome="reauth_required", ..., detail="refresh_rejected")
except ConnectivityError:
    return RenewalOutcome(outcome="transient_failure", ..., detail="provider_unreachable")
except Exception:
    return RenewalOutcome(outcome="reauth_required", ..., detail="refresh_rejected")

# 2xx probe: a renewed outcome must correspond to a store write
if store_path is not None:
    remaining = _seconds_from_store(store_path)
    if remaining is None or remaining <= ACCESS_MARGIN:
        return RenewalOutcome(outcome="reauth_required", ..., detail="renewal_unverified")
return _make_renewed_outcome(store_path)
```

Startup validation (`src/schwab_mcp/server.py`, step 4):

```python
response = retry_call(client.linked_accounts, retries=1)
response_json(response)   # 401/403 → ReauthorizationRequiredError; 5xx → ConnectivityError
```

## Tests Added or Updated

- `tests/unit/test_renewal.py::TestRenew::test_probe_unauthorized_response_maps_to_reauth_required[401|403]` — a 401/403 `Response` from the probe (schwabdev never raises on HTTP errors) → `reauth_required`/`refresh_rejected`; the regression test for the reported phantom `renewal_success`.
- `tests/unit/test_renewal.py::TestRenew::test_probe_server_error_maps_to_transient_failure[500|503]` — 5xx probe response → `transient_failure` (retryable), not `reauth_required`.
- `tests/unit/test_renewal.py::TestRenew::test_probe_success_with_stale_store_is_reauth_required` — Issue 3 consistency: 2xx probe with a store that was never written → `reauth_required`/`renewal_unverified`, never `renewed` with `expires_in_seconds: null`.
- `tests/unit/test_renewal.py::TestRenew::test_renewed_via_tie_breaker_probe` — updated to be faithful: the "other process already renewed" case now writes a fresh token set to the store before returning `False` from `update_tokens()`, and asserts `expires_in_seconds` comes from that store (previously it always asserted `renewed` regardless of store state, which masked the bug).
- `tests/integration/test_failures.py::TestUnauthorizedResponseDuringStartupValidation::test_serve_unauthorized_response_exits_4[401|403]` — serve startup validation gets a 401/403 Response → exit 4, `renewal_failure outcome=reauth_required`, and NO `renewal_success` event.
- `tests/integration/test_failures.py::TestUnauthorizedResponseDuringStartupValidation::test_serve_unauthorized_response_not_retried` — a deterministic 401 is not retried (exactly one `linked_accounts()` call).
- `tests/integration/test_auth.py::test_auth_success_warns_other_installations_revoked` — post-success stderr warning and `auth_success` detail mention the app-key revocation (Issue 2).

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_renewal.py tests/integration/test_renew.py tests/integration/test_renewal_flow.py -q` → 52 passed
  - `uv run pytest tests/integration/test_failures.py tests/integration/test_serve.py tests/integration/test_auth.py -q` → 86 passed
  - `uv run pytest -q` (full suite, commit gate) → **1678 passed, 0 skipped**
- Manual checks: no live-API reproduction (would require a real revoked token set); the regression is pinned by the unit tests above using the real schwabdev response shape (`requests.Response`-like object with `status_code`, non-raising).

## Deviations from Assessment

- **Issue 2, item 2 (asymmetry detail `refresh_rejected_but_access_valid`) deferred.** Detecting "API OK now, refresh dead" at renewal time is not reachable through the current flow: the margin short-circuit returns `not_needed` whenever the stored access token is still valid, so `renew` never observes that asymmetry. Surfacing it would require hooking the tool-path 401/renewal boundary, which is a larger change than this fix warrants. Recorded as a follow-up; the `renewal_unverified` detail covers the verifiable part of the phantom path.
- **5xx probe mapping decision**: the assessment left the 5xx classification as an open question. Implemented as `transient_failure`/`provider_unreachable` (retryable, exit 7) — a provider outage is not evidence of a dead refresh credential — pinned by `test_probe_server_error_maps_to_transient_failure`. The `reauth_required`-on-any-exception catch-all remains for unexpected error types (conservative, as before).
- **Contract vocabulary updated**: added `renewal_unverified` to the `reauth_required` detail enum in `specs/002-automated-token-renewal/contracts/cli.md` and `docs/tools.md` (the assessment anticipated a vocabulary change under Risks). `reauth_needed` was already in `renewal.py`/`docs/tools.md` but missing from the contract table; that pre-existing drift was not touched.

## Follow-ups

- Consider surfacing the `refresh_rejected_but_access_valid` asymmetry at the tool-call boundary (Issue 2, item 2) — e.g. when a `linked_accounts()`-validated session is followed by a refresh rejection.
- Monitor live behavior after deploy: with a real revoked token set, `renew` should now exit 3 with `detail: refresh_rejected` (matches the 11:53/12:32/12:35 observations).
- The 12:32 revocation points to a second installation holding the same app key (unconfirmed) — verify the deployment topology; if confirmed, adopt one app key per installation per `docs/usage.md`.
