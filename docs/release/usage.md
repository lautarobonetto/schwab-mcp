# Daily usage

How to connect your AI client to the server and what the tools do.

## Connect your AI client

The server speaks MCP over **stdio**: your AI client starts it as a local
process and talks to it through that process's standard input/output. No
ports are opened and no configuration file for the server is needed beyond
the environment variables.

Add a server entry to your AI client's MCP configuration (JSON), adjusting
the paths to your machine:

```json
{
  "mcpServers": {
    "schwab": {
      "command": "/full/path/to/schwab-mcp-<version>/.venv/bin/schwab-mcp",
      "args": ["serve"],
      "env": {
        "SCHWAB_APP_KEY": "your-app-key",
        "SCHWAB_APP_SECRET": "your-app-secret",
        "SCHWAB_CALLBACK_URL": "https://127.0.0.1"
      }
    }
  }
}
```

Restart (or reload) your AI client afterwards.

**Expected outcome**: the client shows a connected `schwab` server with
three tools: `get_open_positions`, `get_transaction_history`,
`get_option_chain`.

> Tip: use the absolute path to the `schwab-mcp` binary inside `.venv`
> (shown above) so the client does not depend on a shell environment. You
> can find that path with `ls .venv/bin/schwab-mcp` from the package
> folder.

## Available tools

All tools are **read-only**: they never place orders or move money.

| Tool | What it does | Example prompts |
|------|--------------|-----------------|
| `get_open_positions` | Current positions of your account (symbol, quantity, cost, market value, P&L). | "Show my open positions." — "What is my exposure in NVDA?" |
| `get_transaction_history` | Past movements (trades, dividends, fees, transfers) with filters by date and symbol. | "List May's transactions." — "Show all MSFT trades this year." |
| `get_option_chain` | Option chain for an underlying with filters (side, expiration window, target delta). | "Show the SPY put chain for the next 45 days near delta −0.30." |

If a tool returns an error, your AI client will show the error message —
[troubleshooting.md](troubleshooting.md) maps the common ones to fixes.

## Automatic token renewal

Access tokens expire on Schwab's schedule; the server **renews them
automatically** in the background (and at startup) using the stored
refresh token. Under normal operation there is nothing for you to do.

You only need to act when the credentials themselves can no longer be
renewed (for example after Schwab invalidates the refresh token):

- `schwab-mcp auth-status` reports `"state": "reauth_required"`, or
- tools return an authentication error.

In that case, re-run `schwab-mcp auth` once (see
[first-run-authentication.md](first-run-authentication.md)).

## Configuration

| Environment variable | Default | Meaning |
|----------------------|---------|---------|
| `SCHWAB_APP_KEY` | — (required) | App Key of your developer application. |
| `SCHWAB_APP_SECRET` | — (required) | Secret of your developer application. |
| `SCHWAB_CALLBACK_URL` | `https://127.0.0.1` | Callback URL registered in your developer application. |
| `SCHWAB_TOKEN_DB` | `~/.schwab-mcp/tokens.db` | Where tokens are stored. Keep this outside the package folder — it survives upgrades. |

The `env` block of your AI client's server entry (see above) is the usual
place to set these.

## Privacy and safety

- The server is local-only: it communicates exclusively over stdio and
  with Schwab's official API endpoints.
- Tokens are stored only in the token database on your machine and are
  never printed in tool outputs or logs.
- Never paste tokens, your app Secret, or `tokens.db` into a chat — with
  your AI client or anyone else.
