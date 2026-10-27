# schwab-mcp

A **local MCP server (stdio)** for accessing [Charles Schwab](https://www.schwab.com)
account information from an AI client: positions, transaction history, and
option chains. Everything runs on your machine: no incoming sockets, and
credentials that never leave your computer.

## Documentation

| Topic | Where |
|-------|-------|
| Installation and setup | [docs/installation.md](docs/installation.md) |
| Usage, authorization, and troubleshooting | [docs/usage.md](docs/usage.md) |
| Tools reference for AI agents | [docs/tools.md](docs/tools.md) |
| Change history | [docs/CHANGELOG.md](docs/CHANGELOG.md) |
| **Release / distribution to recipients** | [docs/release-maintenance.md](docs/release-maintenance.md) |

## Commands

```sh
uv sync                        # set up the environment
uv run pytest                  # full test suite
uv run schwab-mcp auth         # interactive authorization
uv run schwab-mcp serve        # MCP server over stdio
uv run schwab-mcp auth-status  # local credential diagnostics
uv run schwab-mcp renew        # explicit renewal
```

## Package for recipients

Recipients who only receive the distribution package follow the English
manuals bundled inside the archive (also in
[docs/release/](docs/release/README.md)). The package is built with
`uv run schwab-mcp-release build` — see
[docs/release-maintenance.md](docs/release-maintenance.md).

## Credential safety

Schwab credentials and tokens live only in
`~/.schwab-mcp/tokens.db` (configurable), never in logs, outputs, or
the repository. The project constitution governs all changes:
[.specify/memory/constitution.md](.specify/memory/constitution.md).