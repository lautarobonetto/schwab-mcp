# Installation guide

Installation and configuration of `schwab-mcp`, the local stdio MCP
server for accessing the Schwab API.

> **Did you receive a distribution package** (a `schwab-mcp-<version>.zip`
> instead of this repository)? This guide is not for you: follow the
> `README.md` included in the package, which starts from
> [docs/release/README.md](./release/README.md) in the maintainer's repo.

## Requirements

- **Python 3.11 or higher** (required by the `schwabdev` library).
- **[uv](https://docs.astral.sh/uv/)** to manage the environment and
  dependencies.
- A **registered and approved application** on
  [developer.schwab.com](https://developer.schwab.com). Schwab's manual
  approval may take several days: start this process first.
- macOS or Linux (the authorization lock uses `fcntl`).

## 1. Install the project

```sh
git clone https://github.com/lautarobonetto/schwab-mcp.git schwab-mcp
cd schwab-mcp
uv sync
```

`uv sync` creates the virtual environment and installs `schwabdev`, the
MCP SDK and the test tools.

## 2. Configure the application in the Schwab portal

On [developer.schwab.com](https://developer.schwab.com) → **My Apps**:

1. The app must be in the **`Ready for Use`** state. `Approved - Pending`
   states mean "under manual review": while it lasts, OAuth login fails
   with unclear errors (for example `4001 Session rejected`).
2. Add **both APIs** to the app: *Accounts and Trading Production* and
   *Market Data Production*.
3. Callback URL: `https://127.0.0.1` — **register the exact form the
   portal demands** (some apps require the trailing slash
   `https://127.0.0.1/`; without it the portal marks the app as in
   error). Either form works: `load_config()` normalizes the local value
   by stripping trailing slashes, because the `schwabdev` library
   rejects callbacks that end in `/`.
4. Copy the **App Key** and **App Secret** from this same app. If you
   have several apps in the portal, verify that the key and secret
   belong to the same one: mixing them produces failures that are hard
   to diagnose.

## 3. Credentials

Credentials are read **exclusively from environment variables**
(FR-008). Store them in a file **outside the repository**, never
committed:

```sh
mkdir -p ~/.schwab-mcp && chmod 700 ~/.schwab-mcp
cat > ~/.schwab-mcp/env <<'EOF'
export SCHWAB_APP_KEY=YOUR_APP_KEY
export SCHWAB_APP_SECRET=YOUR_APP_SECRET
export SCHWAB_CALLBACK_URL=https://127.0.0.1
EOF
chmod 600 ~/.schwab-mcp/env
```

| Variable | Required | Default | Description |
|----------|-------------|---------|-------------|
| `SCHWAB_APP_KEY` | yes | — | App key (client ID) of your Schwab app |
| `SCHWAB_APP_SECRET` | yes | — | App secret, from the **same** app |
| `SCHWAB_CALLBACK_URL` | no | `https://127.0.0.1` | Callback registered in the portal. `https` required; the trailing slash is optional (it is normalized automatically) |
| `SCHWAB_TOKEN_DB` | no | `~/.schwab-mcp/tokens.db` | Path of the token store (SQLite). Outside the repo; permissions forced to `0o600` |

## 4. Load the credentials into the shell

The program **does not read the file** `~/.schwab-mcp/env`: it reads
environment variables of the process. The file is just the mechanism
for loading them:

```sh
set -a; source ~/.schwab-mcp/env; set +a
```

> **Golden rule**: every time you edit the file, or in **every new
> terminal**, run `source` again. The shell keeps stale values from
> previous sessions and mixing them produces confusing errors. Before
> running any command, verify:
>
> ```sh
> echo "$SCHWAB_APP_KEY"       # the correct key
> echo "$SCHWAB_CALLBACK_URL"  # the same URL registered in the portal (with or without trailing slash)
> ```

## 5. Verify the installation

```sh
uv run schwab-mcp --help      # must list the subcommands: auth, serve, renew, auth-status
uv run pytest -q              # full suite: all tests green
```

Besides `auth` and `serve`, the CLI exposes the
[`renew` and `auth-status`](./usage.md#renewal-commands) commands for
automatic token renewal and offline status verification.

## Next step

- [Usage guide](./usage.md) — first authorization, `serve`, connecting
  an MCP client and troubleshooting.