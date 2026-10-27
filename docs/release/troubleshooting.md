# Troubleshooting

Most problems are solved here without contacting anyone. Work top to
bottom: identify your symptom, apply the resolution, and check the
expected outcome.

## Symptom → resolution

| Symptom | Likely cause | Resolution |
|---------|--------------|------------|
| `install.sh` stops with `ERROR: python3 not found...` or `ERROR: Python 3.11 or newer is required...` | Missing or too-old Python | See "Prerequisites" in [installation.md](installation.md): install Python 3.11+ and re-run `./install.sh`. |
| `install.sh` stops with any other `ERROR:` line | See the message table | Each message names its resolution section in [installation.md](installation.md) ("What each install-script error means"). |
| `schwab-mcp auth` exits immediately with a configuration error | `SCHWAB_APP_KEY` / `SCHWAB_APP_SECRET` not set in this shell | Export both variables again (see [first-run-authentication.md](first-run-authentication.md), Step 1) and retry. |
| `schwab-mcp auth` fails after pasting the redirect URL | Wrong/expired URL paste, or rejected app credentials | Re-run `schwab-mcp auth` and paste the fresh, complete URL. If it fails again, re-check your App Key/Secret in the Schwab developer portal. |
| Browser never opened during auth | Headless machine or no default browser | Copy the printed authorization URL into any browser manually. |
| AI client shows the server as disconnected or missing | Wrong `command` path in the client config, or the venv is not installed | Check the absolute path in the client config (see [usage.md](usage.md)); re-run `./install.sh` from the package folder. |
| AI client connects but a tool returns an authentication error | Tokens expired and could not be renewed | Run `schwab-mcp auth-status`; if `"state": "reauth_required"`, re-run `schwab-mcp auth` once. |
| After an upgrade, tools fail or the old version still runs | Old environment still active, or upgrade run from the wrong folder | `deactivate`, then `source <new-package-folder>/.venv/bin/activate` and check `schwab-mcp --help`. Your tokens are preserved (`~/.schwab-mcp/tokens.db`). |
| `another auth already running` | A previous auth is still open | Close the other terminal and retry. |

## Diagnostic commands

**Version** (include this in every report):

```sh
schwab-mcp --help
```

**Authentication status** — local read, no network, answers in one shot:

```sh
schwab-mcp auth-status
```

**Expected outcome**: one JSON line, for example:

```json
{"state": "valid", "access_expires_in_seconds": 1500, "refresh_expires_in_seconds": 600000}
```

How to read it (safe — it never contains secrets):

| Field | Meaning |
|-------|---------|
| `"state": "valid"` | Credentials work; nothing to do. |
| `"state": "reauth_required"` | Run `schwab-mcp auth` once again. |
| `access_expires_in_seconds` | Remaining access-token lifetime; renewals are automatic. |
| `refresh_expires_in_seconds` | Remaining refresh lifetime; when it runs low, plan a `schwab-mcp auth`. |

Exit codes: `0` = valid, `3` = reauth required.

## If you still need help — what to report and what NEVER to share

**Report** (all of it is safe):

- The version from `schwab-mcp --help`.
- Your operating system and Python version (`python3 --version`).
- The symptom, the exact command you ran, and its exact output.
- The output of `schwab-mcp auth-status`.
- Steps that reproduce the problem.

**NEVER share** (none of it is needed to help you):

- The file `tokens.db` (or anything from `~/.schwab-mcp/`).
- Your `SCHWAB_APP_SECRET` (the app Secret).
- Access, refresh, or ID tokens of any kind.
- Authorization/redirect URLs you pasted (they contain one-time codes).
