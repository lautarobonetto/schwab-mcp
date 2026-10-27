# Usage guide

How to authorize, operate and troubleshoot `schwab-mcp`. We assume the
installation is complete as described in the
[installation guide](./installation.md).

## Commands

| Command | Purpose |
|---------|----------|
| `uv run schwab-mcp --help` | Help; **shows the installed version** — always include it when reporting a problem |
| `uv run schwab-mcp auth` | Interactive authorization (browser + URL paste) |
| `uv run schwab-mcp serve` | MCP server over stdio, headless |

## First authorization

```sh
set -a; source ~/.schwab-mcp/env; set +a
uv run schwab-mcp auth
```

The flow is **paste-the-redirect-URL**: the server never opens inbound
sockets; the browser redirect is captured by hand.

1. The CLI validates the configuration and acquires the authorization
   lock.
2. It prints the **full authorization URL** (it includes the client_id —
   public by OAuth design) and opens the browser.
3. Log in to Schwab with your **brokerage** credentials (not the
   developer portal ones) and approve the app; complete the 2FA if
   prompted.
4. The browser tries to go to `https://127.0.0.1/?code=...&session=...`
   and **the connection fails**. This is expected: nothing is listening.
5. Copy the **full URL from the address bar** and paste it into the
   `Paste the redirect URL:` prompt in the terminal.
6. The CLI performs the code exchange and saves the token set.

**Expected result**: `Authorization successful. Schwab API access is
configured.` and exit code `0`.

Verification:

```sh
ls -l ~/.schwab-mcp/tokens.db   # exists, permissions -rw------- (600)
```

### Golden rules of the flow

- **One single run**: the URL you open in the browser and the terminal
  where you paste the redirect must belong to **the same run** of
  `auth`. Mixing URLs from previous runs produces
  `invalid_grant: RedirectURI does not match` in the exchange.
- **No stale tabs**: close every Schwab tab before starting; URLs from
  previous attempts pollute the flow.
- **If login rejects the session** (`error_code: 4001`, `Session
  rejected` / `assertion_rejected`) with the app in `Ready for Use`:
  these are stale browser cookies. Copy the URL printed in the terminal
  and open it in an **incognito window**, or clear the cookies of
  `schwab.com` / `schwabapi.com`.

## Daily use: the MCP server

```sh
uv run schwab-mcp serve
```

On startup, the server:

1. Validates the configuration (fail fast).
2. Verifies the token store: missing or corrupt → exits with a clear
   message.
3. Renews the access token if it is expired (`renewal_success` event).
4. Validates access with a real read against the API (proactive, < 5 s).
5. Connects the stdio transport and **waits for an MCP client**.

In a terminal without a client, the process simply stays alive waiting
on stdin — that is the correct behavior. Stop it with `Ctrl+C`.

`serve` never opens a browser, never asks for input and never starts an
implicit authorization flow. If re-authorization is needed, it exits
with exit code `4` and the message `Run schwab-mcp auth`.

### Connect an MCP client

Configure the server in your MCP client (Claude Desktop, opencode,
etc.):

```json
{
  "mcpServers": {
    "schwab": {
      "command": "uv",
      "args": [
        "run", "--directory", "/path/to/schwab-mcp", "schwab-mcp", "serve"
      ],
      "env": {
        "SCHWAB_APP_KEY": "YOUR_APP_KEY",
        "SCHWAB_APP_SECRET": "YOUR_APP_SECRET",
        "SCHWAB_CALLBACK_URL": "https://127.0.0.1"
      }
    }
  }
}
```

The `env` block replaces the `~/.schwab-mcp/env` file for the server
process: the MCP client launches `serve` with its own environment.

## Token lifecycle

- **Access token**: ~30 minutes. Renews itself, with no intervention
  (`renewal_success` / `renewal_failure` events on stderr).
- **Refresh token**: ~7 days. Once expired, you must re-authorize:

```sh
uv run schwab-mcp auth
```

A failed re-auth attempt does not touch the existing token set: if the
new authorization does not complete, the current tokens remain intact.

## Renewal commands

Designed for non-interactive agents. Neither opens a browser, reads
stdin nor opens sockets. Both print exactly **one JSON line** on stdout
and use stderr for auxiliary messages.

The full contract is in
[specs/002-automated-token-renewal/contracts/cli.md](../specs/002-automated-token-renewal/contracts/cli.md).
The detailed reference for AI agents (JSON fields, semantics of each
outcome, decision playbook) is in
[docs/tools.md](./tools.md).

### `schwab-mcp renew`

Renews the access token non-interactively. Loads configuration,
verifies the store, and attempts the refresh with up to 2 retries
against transient failures.

```sh
uv run schwab-mcp renew
```

**Exit codes:**

| Code | Meaning |
|--------|------------|
| 0 | `renewed` or `not_needed` (still valid) |
| 2 | Missing or malformed configuration |
| 3 | Re-authorization required: `reauth_required` (run `schwab-mcp auth`) |
| 6 | Another renewal or authorization already in progress (`busy`) |
| 7 | Transient error: `transient_failure` (the agent may retry later) |

### `schwab-mcp auth-status`

**Local** authentication health check (no network). Reads the token
store and returns the status within ≤ 2 seconds.

```sh
uv run schwab-mcp auth-status
```

**Exit codes:**

| Code | Meaning |
|--------|------------|
| 0 | `valid` (the fields indicate remaining time) |
| 2 | Missing or malformed configuration |
| 3 | Re-authorization required: `reauth_required` (store missing or corrupt) |

## Failure modes

Each failure prints its own, actionable message and exits with a
specific code. None of them hang or show tracebacks.

| Failure | Exit | Recovery |
|-------|------|--------------|
| Missing `SCHWAB_APP_KEY` / `SCHWAB_APP_SECRET` | 2 | Fill in `~/.schwab-mcp/env` and re-source |
| Invalid configuration values | 2 | Fix the values in the env |
| Authorization canceled | 3 | Re-run `schwab-mcp auth` |
| Re-authorization required | 4 | Run `schwab-mcp auth` to renew tokens |
| Corrupt token store | 5 | Run `schwab-mcp auth` (the store is treated as missing) |
| Concurrent authorization | 6 | Another authorization is already running; wait for it |
| Connectivity failure | 7 | Check the network and retry; the store is untouched |

## Troubleshooting

| Symptom | Cause | Solution |
|---------|-------|---------|
| `ValueError: callback_url cannot be a path (endswith "/")` | Old package version: the trailing slash is already normalized in `load_config()` | Update the code; with the current version both forms work |
| `invalid_grant: RedirectURI does not match` | You mixed URLs from different runs | Fresh run: open the URL printed by **that** run and paste the redirect into **that same** terminal |
| `4001 Session rejected` at login | Stale browser cookies (with app `Ready for Use`) | Incognito window with the printed URL, or clear cookies of `schwab.com` |
| The CLI uses values you already changed in the env | The shell keeps stale variables | `set -a; source ~/.schwab-mcp/env; set +a` and verify with `echo` |
| `invalid_client` in the exchange | App key and app secret from different apps | Copy **both** from the same app in the portal |
| Review that never finishes | `Approved - Pending` state | Wait for `Ready for Use` in the portal; if it persists, `traderapi@schwab.com` |

## Security

- Credentials only via environment, in memory, never written to disk.
- Token store and env with `0o600` permissions; directory `0o700`.
- Redaction filter on all logs: app secret, tokens and authorization
  codes never appear in the output.
- No inbound sockets: the paste-the-redirect-URL design removes the
  local HTTP listener.
- Read-only scope: the authorized token has the minimum necessary
  privilege.

## References

- [Interface for AI agents](./tools.md) — full reference of commands
  and JSON fields for agent consumption
- [Changelog](./CHANGELOG.md) — code progress per version
- [Installation guide](./installation.md)
- [Spec quickstart](../specs/001-schwab-oauth-access/quickstart.md)
  — end-to-end validation scenarios
- [CLI contract](../specs/001-schwab-oauth-access/contracts/cli.md)
- [Configuration contract](../specs/001-schwab-oauth-access/contracts/configuration.md)
- [Events contract](../specs/001-schwab-oauth-access/contracts/events.md)