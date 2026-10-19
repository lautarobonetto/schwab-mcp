# Contract: Configuration (Environment Variables)

**Feature**: `001-schwab-oauth-access`

Application credentials and tuning are supplied exclusively through
environment variables (FR-008). They may be sourced from an env file
outside the repository, e.g.:

```sh
set -a; source ~/.schwab-mcp/env; set +a   # file outside the repo, chmod 600
```

## Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SCHWAB_APP_KEY` | yes | — | Owner's Schwab developer app key (client id). Never logged (FR-006). |
| `SCHWAB_APP_SECRET` | yes | — | App secret from app approval. Never logged (FR-006). |
| `SCHWAB_CALLBACK_URL` | no | `https://127.0.0.1` | Callback/redirect URI **as registered in the developer portal**. Must match the registration exactly (no trailing slash, https). It is never connected to by this server — the auth flow is paste-the-redirect-URL, so no inbound socket is opened. |
| `SCHWAB_TOKEN_DB` | no | `~/.schwab-mcp/tokens.db` | Token store path (FR-012). Must be outside the repo; enforced permissions `0o600` (file) / `0o700` (directory). |

Derived internal default: advisory auth lock at
`~/.schwab-mcp/auth.lock` (alongside the token DB; not independently
configurable — YAGNI).

## Validation rules (fail fast at process start, both subcommands)

1. `SCHWAB_APP_KEY` / `SCHWAB_APP_SECRET` present and non-empty after
   stripping whitespace → otherwise `MissingConfigError` (exit 2).
2. Format checks (even lengths, combined ≥ 32 chars; https callback URL
   without trailing slash) are delegated to schwabdev and its
   `ValueError` is mapped to `InvalidConfigError` (exit 2) — no duplicated
   validation logic (DRY).
3. Malformed `SCHWAB_TOKEN_DB` that is clearly invalid (ends with `/`,
   empty) → `InvalidConfigError` before touching the filesystem.

## Security invariants

- Credential values are read once into memory, registered with the
  redaction filter, and never written to disk, logs, error messages, or
  tool output (FR-006).
- The repo must never contain these values in any form (tests, docs,
  scripts); `.gitignore` excludes `tmp/` and any local env artifacts.
- Nothing here reads or writes `~/.schwabdev/env.json` (schwabdev's
  optional global config) — this project always passes explicit values,
  so the library's global fallback cannot silently inject different
  credentials.
