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
| Change history | [docs/CHANGELOG.md](docs/CHANGELOG.md) |

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
[.specify/memory/constitution.md](.specify/memory/constitution.md).

## License

[MIT](LICENSE)