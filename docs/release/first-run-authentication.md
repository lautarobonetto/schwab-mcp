# First-run authentication

One-time setup that connects this package to **your own** Charles Schwab
account. Nothing is configured yet until you complete these steps.

## Before you start

You need a Schwab **developer application** — a set of API credentials
that belongs to you:

1. Go to the Schwab developer portal (<https://developer.schwab.com>) and
   sign in with your Schwab account.
2. Register (or open) an application. For the callback (redirect) URL use
   exactly `https://127.0.0.1`.
3. Note the two values the portal shows for your application: the
   **App Key** (also called client ID) and the **Secret** (also called app
   secret). These are *your* credentials — treat the Secret like a
   password.

You will also need your regular Schwab **brokerage** login (the one you
use for the website/app) — not the developer-portal login — when the
browser step appears.

## Step 1 — Configure the credentials

The server reads four environment variables:

| Variable | Required | Meaning |
|----------|----------|---------|
| `SCHWAB_APP_KEY` | yes | The App Key of your developer application. |
| `SCHWAB_APP_SECRET` | yes | The Secret of your developer application. |
| `SCHWAB_CALLBACK_URL` | no | Must match your application's callback URL. Defaults to `https://127.0.0.1`. |
| `SCHWAB_TOKEN_DB` | no | Where credentials are stored. Defaults to `~/.schwab-mcp/tokens.db`. |

For a single session:

```sh
export SCHWAB_APP_KEY="your-app-key"
export SCHWAB_APP_SECRET="your-app-secret"
```

**Expected outcome**: the commands complete silently. (In your AI client
you set the same variables in its configuration instead — see
[usage.md](usage.md).)

## Step 2 — Run the authorization flow

```sh
schwab-mcp auth
```

**Expected outcome, step by step**:

1. The command prints a long `https://api.schwabapp.com/...` **authorization
   URL** and opens your browser at that URL. (The App Key appears inside
   this URL — that is normal and safe: it is the public client ID. The
   secret never appears.)
2. In the browser, sign in with your Schwab **brokerage** credentials and
   approve the application (complete 2FA if prompted).
3. The browser then tries to open `https://127.0.0.1/?code=...` and shows a
   **"can't connect" / "site can't be reached" page**. This is expected —
   nothing is listening on your machine. The address bar now contains the
   result of the login.
4. Copy the **complete URL** from the address bar and paste it at the
   `Paste the redirect URL:` prompt. Press Enter.
5. The command prints `Authorization successful. Schwab API access is
   configured.`

The authorization can take a few seconds to complete after you paste.

## Where your credentials are stored

- Tokens are stored **only** in `~/.schwab-mcp/tokens.db` (or the path set
  in `SCHWAB_TOKEN_DB`) on your own machine, with restrictive file
  permissions.
- They are never written to logs, never returned by the tools, and never
  included in this package.
- Nothing is sent anywhere except Schwab's own API endpoints.

**Never** share `tokens.db`, your app Secret, or any token — see
[troubleshooting.md](troubleshooting.md) for what *is* safe to share.

## When something goes wrong

| Symptom | Likely cause | Resolution |
|---------|--------------|------------|
| Command exits immediately with a configuration error naming a missing variable | `SCHWAB_APP_KEY` / `SCHWAB_APP_SECRET` not exported | Export both variables (Step 1) and re-run `schwab-mcp auth`. |
| Browser shows Schwab rejecting the login or the app | Wrong App Key/Secret, or the app is not approved yet in the developer portal | Re-check the values in the developer portal; fix the exports and re-run `schwab-mcp auth`. |
| No browser opened | Headless machine or no default browser | Copy the printed authorization URL and open it manually in any browser, then continue at step 3 above. |
| `Authorization cancelled` after pasting (or you pasted an empty URL) | Pasted too late, wrong URL, or an empty prompt | Re-run `schwab-mcp auth` and paste the fresh, complete URL. |
| `another auth already running` | A previous `schwab-mcp auth` is still open | Close the other terminal (or wait for it) and retry. |

More symptoms and diagnostics: [troubleshooting.md](troubleshooting.md).
