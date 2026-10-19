# Quickstart: Automated Token Renewal Validation

**Feature**: `002-automated-token-renewal`

Runnable validation scenarios proving the feature end-to-end. Contract
details: [contracts/cli.md](./contracts/cli.md) · events:
[contracts/events.md](./contracts/events.md) · structures:
[data-model.md](./data-model.md).

## Prerequisites

1. Python 3.11+ environment with the project installed (`uv sync`).
2. Environment variables `SCHWAB_APP_KEY` and `SCHWAB_APP_SECRET` set
   (as for feature 001).
3. A token store from a completed `schwab-mcp auth` (feature 001 flow).
4. Tests must not touch the real API: scenarios use stub clients and a
   temporary token DB under `tmp/` (never committed).

## Test suite (primary validation)

```bash
uv run pytest                        # full suite, green-before-commit gate
uv run pytest tests/unit/test_renewal.py -v
uv run pytest tests/integration/test_renew.py tests/integration/test_auth_status.py -v
uv run pytest tests/performance/test_renewal_budget.py tests/performance/test_output_budget.py -v
```

Expected: all pass; performance tests assert the SC-002 renewal budget
(≤ 10 s worst case: 3 attempts × 3 s timeout + 2 × 0.5 s waits) and the
`auth-status` ≤ 2 s local budget; token-usage tests assert the ≤ 300-byte
single-line JSON result budget (Principle V).

## Scenario 1 — Agent renews with one command (US2 P2)

```bash
# Given a stored credential set whose access credential is stale/expired
uv run schwab-mcp renew
```

Expected: exit `0`, stdout is exactly one JSON line
`{"outcome": "renewed", "expires_in_seconds": <n>, "retryable": false, "detail": "access_renewed"}`,
stderr carries `renew_start` → `renewal_success outcome=ok`. No browser,
no prompt, no URL anywhere.

## Scenario 2 — Renewal unnecessary is a success, not an error (US2 AC2)

```bash
uv run schwab-mcp renew   # immediately again, credential still fresh
```

Expected: exit `0`, `{"outcome": "not_needed", ...}`; no provider call
was made; the valid credential set is untouched.

## Scenario 3 — Health in one query (US3 AC1, FR-008)

```bash
uv run schwab-mcp auth-status
```

Expected: exit `0`,
`{"state": "valid", "access_expires_in_seconds": <n>, "refresh_expires_in_seconds": <n>}`.
With the store absent/corrupted: exit `3` and
`{"state": "reauth_required", ...}` naming `store_absent`/`store_corrupted`.

## Scenario 4 — Re-authorization-required is detectable, never a browser (US3)

Simulate a rejected refresh credential (stubbed client in tests):
`renew` → exit `3`, outcome `reauth_required`, detail `refresh_rejected`;
a repeat run reports the same classification (consistent indication, no
retry storm); stderr shows `renewal_failure outcome=reauth_required`.
Recovery is exactly the 001 interactive `schwab-mcp auth`, after which
`auth-status` reports `valid` with no further agent action.

## Scenario 5 — Transparency of the automatic path (US1 P1, FR-011)

In the unit/integration harness: an operation performed against a stub
client with a stale access credential succeeds; exactly one renewal
occurred; the operation result is unchanged in shape. Verified by the
single-flight tests (concurrent callers share one renewal, FR-005).

## Manual smoke (optional, owner machine)

```bash
uv run schwab-mcp auth-status && uv run schwab-mcp renew
```

Both commands print one JSON line each and exit `0` with a live token
store. Anything else → compare against the exit-code tables in
[contracts/cli.md](./contracts/cli.md).