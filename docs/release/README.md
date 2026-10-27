# schwab-mcp — Release Package

A **local stdio MCP server** that gives your AI client read access to your
Charles Schwab account data: positions, transaction history, and option
chains. Everything runs on your own computer over standard input/output —
the server never opens network ports for incoming connections, and your
credentials never leave your machine.

This package is self-contained: it ships the server (as a Python wheel),
four task manuals, an install script, and integrity checksums.

## Your package version

After installation, the version you are running is printed by:

```sh
schwab-mcp --help
```

Always include this version when you report a problem (see
[troubleshooting.md](manuals/troubleshooting.md)).

## Verify the package integrity (do this first)

Before installing, verify that the archive arrived unmodified. Put
`schwab-mcp-<version>.zip` and `schwab-mcp-<version>.zip.sha256` in the
same directory and run:

- macOS:

  ```sh
  shasum -a 256 -c schwab-mcp-<version>.zip.sha256
  ```

- Linux:

  ```sh
  sha256sum -c schwab-mcp-<version>.zip.sha256
  ```

**Expected outcome**: one line ending in `OK` (for example
`schwab-mcp-<version>.zip: OK`, with `<version>` matching your package).
If the line says `FAILED`, do not install —
re-download the package and verify again.

Inside the extracted folder, `SHA256SUMS` lists the checksum of every
individual file, and `manifest.json` lists them with sizes. You can verify
the inner files the same way, from inside `schwab-mcp-<version>/`:

```sh
shasum -a 256 -c SHA256SUMS        # macOS (Linux: sha256sum -c SHA256SUMS)
```

## Where to start

Read in this order:

1. [manuals/installation.md](manuals/installation.md) — prerequisites,
   installation, and in-place upgrades.
2. [manuals/first-run-authentication.md](manuals/first-run-authentication.md) —
   connect the package to your own Schwab account (one time).
3. [manuals/usage.md](manuals/usage.md) — connect your AI client and use
   the tools day to day.
4. [manuals/troubleshooting.md](manuals/troubleshooting.md) — fix problems
   yourself; know what to report if you cannot.

## Your credentials and your data

- Your Schwab credentials and access tokens are stored **only** in
  `~/.schwab-mcp/tokens.db` on your own machine (a different, configurable
  path is possible — see the usage manual).
- Nothing in this package contains tokens, keys, or account data.
- Never send `tokens.db`, your Schwab app secret, or any token to anyone —
  including when asking for help.
