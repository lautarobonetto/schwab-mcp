# Contract: CLI Commands

**Feature**: `001-schwab-oauth-access`

The project exposes exactly one console script, `schwab-mcp`, with two
subcommands. These commands are the user-facing interface of this feature;
the MCP server exposes **no tools** in this feature (tools arrive in a
later feature).

## `schwab-mcp auth`

One-time (and re-)authorization. Interactive by design; the only command
that may open a browser and read stdin.

```
usage: schwab-mcp auth [-h]
```

### Behavior

1. Loads and validates configuration from the environment (fail fast —
   `MissingConfigError`/`InvalidConfigError` exit before any browser or
   network activity).
2. Acquires an exclusive, non-blocking advisory auth lock
   (`~/.schwab-mcp/auth.lock`); if busy, exits `6` with the
   concurrent-authorization message (FR-011).
3. Prints the authorization URL, opens the system browser at the Schwab
   login page, and prompts the owner to paste the final redirect URL from
   the address bar. If the browser cannot be opened, it prints the URL and
   continues with the paste prompt (no hang: the prompt is always reachable).
4. Exchanges the pasted redirect URL/code via schwabdev; on success the
   token set is written to the configured token DB (chmod 600) and the
   command prints a success confirmation (no secrets) and exits `0`.
5. On cancel/failure, exits nonzero with the mapped FR-007 message.
   An existing valid token set is not modified until a new authorization
   completes successfully (FR-010).

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Authorization succeeded; token set stored |
| 2 | Missing or malformed configuration |
| 3 | Authorization cancelled/failed before completion |
| 6 | Another authorization is already running |
| 7 | Connectivity failure exchanging the code (retryable) |

### Output guarantees

- stdout/stderr contain **no** app secret, token, or authorization code,
  and no app key outside the displayed authorization URL (FR-006; redaction
  filter active).
- The authorization URL is displayed to the owner **in full** (client_id
  included — public by OAuth design, amended FR-006) so it can be visited
  or pasted into any browser as-is; it is never logged to any persistent
  sink.
- Auth events (`auth_start`, `auth_success`, `auth_failure`) are emitted to
  stderr per [events.md](./events.md).

## `schwab-mcp serve`

Headless stdio MCP server. Never opens a browser, never reads stdin beyond
the MCP stdio channel, never triggers an implicit authorization flow
(FR-001).

```
usage: schwab-mcp serve [-h]
```

### Behavior

1. Loads and validates configuration from the environment (fail fast).
2. Peeks at the configured token store:
   - store absent → exit `4` with the "run `schwab-mcp auth`" message;
   - store unreadable/corrupt → treated as absent per FR-009 → exit `5`
     with the re-auth message (store not deleted).
3. Instantiates the schwabdev client (loads tokens; refreshes the access
   token if it has expired; the internal `call_on_auth` hook is wired to
   raise `ReauthorizationRequiredError` so no browser/prompt can ever
   occur in serve context).
4. Proactively verifies live access with one `linked_accounts()` read
   (FR-013) — must complete within the 5 s ready budget (SC-004).
5. Only then connects the MCP stdio transport and signals ready. On
   renewal failure before ready, exits with the mapped FR-007 code.
6. Renewal failure *after* ready is surfaced to the next requesting MCP
   client as a tool-level error message pointing to `schwab-mcp auth`
   (no secrets); the process does not self-restart the browser flow.

### Exit codes (pre-ready failures)

| Code | Meaning |
|------|---------|
| 2 | Missing or malformed configuration |
| 4 | Re-authorization required (no usable token set) |
| 5 | Corrupted token store (treated as absent) |
| 7 | Connectivity failure during startup validation |

### Output guarantees

- stdout is reserved exclusively for the MCP protocol channel.
- All logs/events go to stderr ([events.md](./events.md)); zero credential
  material anywhere (FR-006).
- No inbound network sockets are ever opened (constitution; paste-URL auth
  design).

## Shared guarantees

- No subcommand hangs: every failure path is a bounded exit; the only
  blocking waits are the interactive paste prompt (`auth`) and normal
  stdio serving (`serve`).
- Identical config parsing and error taxonomy for both commands
  (single implementation — DRY).
