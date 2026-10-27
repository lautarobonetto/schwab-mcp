# schwab-mcp

A **local MCP server (stdio)** for accessing [Charles Schwab](https://www.schwab.com)
account information from an AI client: positions, transaction history, and
option chains. Everything runs on your machine: no incoming sockets, and
credentials that never leave your computer.

## Disclaimer

This is an independent, **unofficial** project. It is not affiliated with,
endorsed by, or sponsored by Charles Schwab & Co., Inc. "Schwab" and related
marks belong to their respective owners.

- **Read-only by design**: the exposed tools only read positions,
  transaction history, and option chains — no order placement or any other
  write operation.
- You are responsible for complying with the Schwab developer program terms
  and API policies that govern your own application keys.
- No warranty: the software is provided "as is" (see [LICENSE](LICENSE)).
  Nothing here is financial, investment, tax, or legal advice.

## Documentation

| Topic | Where |
|-------|-------|
| Installation and setup | [docs/installation.md](docs/installation.md) |
| Usage, authorization, and troubleshooting | [docs/usage.md](docs/usage.md) |
| Tools reference for AI agents | [docs/tools.md](docs/tools.md) |
| Development guide (setup and workflow) | [docs/development.md](docs/development.md) |
| Change history | [docs/CHANGELOG.md](docs/CHANGELOG.md) |

## Tools

The MCP server (`schwab-mcp serve`) exposes **four read-only tools**:

| Tool | What it does |
|------|--------------|
| `get_open_positions` | All effective holdings of every linked account in a single call. |
| `get_transaction_history` | Movements of all linked accounts in a date range, with an optional instrument filter and pagination. |
| `get_option_chain` | Full option chain of an underlying in one call, with strike, delta, and DTE filters, including the Greeks. |
| `get_quotes` | Current quotes for 1..20 symbols (equities, ETFs, indexes, option contracts) in one call: last, bid/ask, volume, net change, freshness, last-trade time. |

Every tool returns a structured JSON result with an explicit `outcome`
(`ok`, `transient_failure`, `reauth_required`, …), so an agent can act
without human intervention.

The tool set is intentionally small and basic — but it is fast,
token-efficient, and composable: from just positions, history, quotes,
and option chains, an agent can run surprisingly sophisticated analyses
(portfolio performance, trade-chain reconstruction, options-strategy
sizing, dividend tracking, and more). We are open to suggestions for
new tools — [open an issue](https://github.com/lautarobonetto/schwab-mcp/issues)
or reach out and tell us what you would like to see next.

### What you can do

- **Positions**: see everything you hold across all linked accounts
  (optionally with the full provider passthrough via `extended: true`).
- **Transaction history**: reconstruct what happened in an account —
  trades, transfers, dividends — filtered by symbol (equities, ETFs,
  option underlyings, or full OCC symbols), paginated at 50 movements
  per page. Maximum window per query: **1 year**.
- **Quotes**: mark any position to market with one small call — current
  price, bid/ask, volume, net change, and an explicit freshness state
  (`realtime` / `delayed` / `closed`) so the agent knows how stale a
  price is without a second call.
- **Option chains**: browse strikes around the money or target a
  delta (e.g. `delta_target: 0.2` for short-strangle legs), bounded by
  DTE, with bid/ask, volume, open interest, IV, and the 5 Greeks.
- All of it **read-only, local, and secret-free**: credentials never
  appear in outputs, and no operation places orders or moves money.

### What you cannot do

- **No write operations**: no order placement, modification, or
  cancellation — the tools only read positions, history, quotes, and
  chains.
- **No streaming or historical market data**: quotes are point-in-time
  snapshots, not streaming feeds, and there is no price-history/chart
  endpoint — no fundamentals, earnings calendars, or dividend dates
  either. For those needs (earnings
  dates, ex-dividends, financial statements, ratios) we recommend
  complementing this MCP with the [FMP](https://site.financialmodelingprep.com/)
  MCP, which covers Schwab's gaps on that front.
- **No account management**: no balances snapshot, bank links, or
  preferences; account identifiers are opaque hashes.
- **Hard limits**: transaction windows longer than 1 year must be
  split into consecutive queries; option chains never return
  expirations beyond a 60-day DTE ceiling (there is a `dte_max`, but
  no `dte_min`).

The exact input/output schema of every tool — field by field, with
error semantics and agent playbooks — lives in
[docs/tools.md](docs/tools.md).

### Examples

Positions of all linked accounts:

```json
{"name": "get_open_positions", "arguments": {}}
```

AAPL movements over three months:

```json
{"name": "get_transaction_history", "arguments": {
  "start_date": "2026-07-01", "end_date": "2026-09-30", "symbol": "AAPL"}}
```

Puts around a −0.20 delta (≤ 5 strikes per expiration, small payload):

```json
{"name": "get_option_chain", "arguments": {
  "symbol": "SPY", "option_type": "puts", "delta_target": 0.2}}
```

Current quotes for a whole portfolio in one call:

```json
{"name": "get_quotes", "arguments": {
  "symbols": ["AAPL", "NOK", "$SPX", "AAPL 261127C350"]}}
```

## Commands

```sh
uv sync                        # set up the environment
uv run pytest                  # full test suite
uv run schwab-mcp auth         # interactive authorization
uv run schwab-mcp serve        # MCP server over stdio
uv run schwab-mcp auth-status  # local credential diagnostics
uv run schwab-mcp renew        # explicit renewal
```

## Credential safety

Schwab credentials and tokens live only in
`~/.schwab-mcp/tokens.db` (configurable), never in logs, outputs, or
the repository. The project constitution governs all changes:
[.specify/memory/constitution.md](.specify/memory/constitution.md);
the project direction and planned future tools live in the spec
roadmap: [.specify/memory/roadmap.md](.specify/memory/roadmap.md).
The MCP is read-only by design: no spec places orders or moves money.

## Contributing

Want to develop on this project? Read the
[development guide](docs/development.md): what to install (uv, OpenCode,
codebase-memory-mcp, Spec Kit), and the spec-driven, test-first
workflow every change must follow. Suggestions for new tools are
welcome — [open an issue](https://github.com/lautarobonetto/schwab-mcp/issues).

## License

[MIT](LICENSE)