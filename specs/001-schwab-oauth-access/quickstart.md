# Quickstart: Schwab OAuth Access — End-to-End Validation

**Feature**: `001-schwab-oauth-access`

This guide validates the OAuth access layer against the real Schwab API.
Automated tests (unit/integration/performance) run hermetically with a
stubbed Schwab client; the live steps below are the owner's acceptance run.

Reference: [contracts/cli.md](./contracts/cli.md) ·
[contracts/configuration.md](./contracts/configuration.md) ·
[data-model.md](./data-model.md)

## Prerequisites

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) installed.
- A **registered and approved** Schwab developer application
  (developer.schwab.com — approval can take days; owner action).
  The app's callback URL must be registered as `https://127.0.0.1`
  (or another https URL you will pass via `SCHWAB_CALLBACK_URL`).
- Your app key and app secret from the developer portal.

## Setup

```sh
# from the repository root
uv sync                                   # create venv + install deps (schwabdev, mcp, pytest)

# credentials in an env file OUTSIDE the repo (chmod 600, never committed)
mkdir -p ~/.schwab-mcp && chmod 700 ~/.schwab-mcp
cat > ~/.schwab-mcp/env <<'EOF'
export SCHWAB_APP_KEY=YOUR_APP_KEY
export SCHWAB_APP_SECRET=YOUR_APP_SECRET
export SCHWAB_CALLBACK_URL=https://127.0.0.1
EOF
chmod 600 ~/.schwab-mcp/env
set -a; source ~/.schwab-mcp/env; set +a
```

## Scenario A — First-time authorization (US1, SC-001)

```sh
uv run schwab-mcp auth
```

1. A Schwab login page opens in your browser; sign in and approve the app.
   If the login page rejects your session with `error_code: 4001`,
   `"Session rejected"` / `assertion_rejected` (and your app status is
   `Ready for Use`), stale browser cookies are the usual cause: copy the
   authorization URL printed in the terminal and retry it in a
   private/incognito window, or clear cookies for `schwab.com` /
   `schwabapi.com` first. The printed URL is complete and usable as-is.
2. The browser is redirected to your callback URL (which fails to connect
   — expected: nothing is listening; this design opens no socket).
3. Copy the full URL from the browser's address bar and paste it at the
   terminal prompt.
4. Expected: `auth_success` confirmation, exit code `0`, and a token store
   created:

```sh
ls -l ~/.schwab-mcp/tokens.db   # exists, permissions -rw------- (600)
```

5. Verify no secrets were printed: no app key/secret/token/code appears in
   the terminal output (SC-003; automated tests assert this continuously).

## Scenario B — Silent reuse and proactive validation (US2, SC-004)

```sh
uv run schwab-mcp serve
```

Expected within 5 seconds (before any MCP client connects): startup
validation succeeds (`linked_accounts()` read) and the server signals
ready on stdio; no browser opens, no prompt appears. Stop it with `Ctrl+C`.

Repeat the start twice more — zero manual logins (SC-002 inside the 7-day
refresh-token window). A live authenticated read succeeds with no
additional steps.

## Scenario C — Failure modes are distinct and actionable (US3, SC-005)

Each check must print its distinct message, exit nonzero, and **not hang**
(Ctrl+C is never needed).

1. **Missing config**
   ```sh
   env -u SCHWAB_APP_KEY -u SCHWAB_APP_SECRET uv run schwab-mcp serve
   ```
   → message: set `SCHWAB_APP_KEY`/`SCHWAB_APP_SECRET` (exit `2`).

2. **Malformed config**
   ```sh
   SCHWAB_APP_KEY=short SCHWAB_APP_SECRET=also uv run schwab-mcp serve
   ```
   → message pointing at the configuration values (exit `2`).

3. **Cancelled authorization**
   ```sh
   mv ~/.schwab-mcp/tokens.db /tmp/ 2>/dev/null || mv ~/.schwab-mcp/tokens.db tmp/
   uv run schwab-mcp auth      # press Enter with empty paste (or Ctrl+C at browser step)
   ```
   → message: how to retry authorization (exit `3`).
   Then restore the store (`mv` it back) or re-run `schwab-mcp auth`.

4. **Re-authorization required** — simulate by temporarily moving
   `tokens.db` away, then:
   ```sh
   uv run schwab-mcp serve
   ```
   → message: run `schwab-mcp auth` (exit `4`); no hang.

5. **Corrupted token store**
   ```sh
   echo "not a database" > ~/.schwab-mcp/tokens.db
   uv run schwab-mcp serve
   ```
   → message: store treated as absent, run `schwab-mcp auth` (exit `5`);
   then re-run Scenario A.

6. **Concurrent authorization**
   ```sh
   uv run schwab-mcp auth &     # first attempt (complete it in the browser)
   uv run schwab-mcp auth       # second attempt while the first is running
   ```
   → second attempt exits immediately: another authorization is already
   running (exit `6`).

7. **Connectivity failure** — disconnect from the network during a
   `serve` start with an expired access token (or block
   `api.schwabapi.com`): one retry, then a clear connectivity message
   (exit `7`); the stored token set is not deleted or corrupted.

Automated equivalents of every scenario above live in `tests/` and run
without network or credentials (stubbed client); see `tests/integration/`
and `tests/unit/` after `/speckit.tasks` + implementation.

## Automated test suite (owner-run gate)

```sh
uv run pytest -q            # full suite green, no skipped tests (constitution gates)
uv run pytest tests/performance -q   # startup-validation within 5 s budget (SC-004)
```

## Leak check (FR-006 / SC-003)

```sh
uv run schwab-mcp auth 2>&1 | grep -c "$SCHWAB_APP_KEY"        # expect 0
uv run pytest tests/unit -q -k redaction                       # redaction filter tests
```

Zero occurrences of the app key/secret/tokens in any output is the pass
condition; the automated suite enforces this with stubbed secrets on every
run.
