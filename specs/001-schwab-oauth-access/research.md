# Research: Schwab OAuth Access

**Feature**: `001-schwab-oauth-access` | **Date**: 2026-10-19

Research performed against the actual `schwabdev` v4 source (`tokens.py`,
`client.py` on GitHub main), the official Schwab developer OAuth guide, and
the `schwab-py` auth documentation (for cross-validation of flow semantics).
No NEEDS CLARIFICATION items remain.

## R1. Library choice for OAuth/token mechanics

- **Decision**: `schwabdev` 4.0.0 (Tyler Bowers, MIT, PyPI
  "Production/Stable", released Aug 2026).
- **Rationale**: Actively maintained (frequent 2024–2026 releases), owns the
  complete OAuth lifecycle we need: authorization-URL construction, code
  exchange, SQLite token persistence, access-token refresh, and
  refresh-coordination locking between instances. Constitution Principle III
  mandates reuse; the assessment (api-engine, Option B) already selected it.
  Hand-rolling OAuth here would duplicate a dangerous, well-documented
  footgun (schwab-py's README explicitly warns against custom OAuth
  callback implementations).
- **Alternatives considered**:
  - `schwab-py` 1.5.1 — no release in ~16 months while the Schwab API has a
    history of breaking changes (tda-api retirement); rejected on
    maintenance risk.
  - Hand-rolled OAuth against `https://api.schwabapi.com/v1/oauth/token` —
    rejected: duplicates a maintained library (violates Principle III) and
    multiplies credential-leak surface.
  - Adopt `jkoelker/schwab-mcp` wholesale — rejected at decide stage: it
    ships trading tools and a much larger surface than the owner's
    read-only, own-the-thin-layer appetite.

## R2. How the "explicit authorization command" wires into schwabdev (US1)

- **Decision**: `schwabdev.Client(..., call_on_auth=<our hook>,
  open_browser_for_auth=False)`. Our `call_on_auth(auth_url)` hook prints
  the URL, opens the system browser, and prompts the owner to paste the
  final redirect URL from the address bar; the hook returns that URL (or a
  raw code), which schwabdev parses and exchanges for the token set.
- **Rationale (source-verified)**: In schwabdev v4, `Tokens.__init__`
  auto-starts the authorization flow whenever the token DB is empty, and
  `_prompt_for_auth` delegates entirely to `call_for_auth` when provided.
  Supplying our own hook is the only supported way to control the flow
  (the old `capture_callback`/`call_on_notify` params were removed in
  v3.0.0). With `open_browser_for_auth=False` we own the browser opening
  and messaging. The server process, by contrast, never reaches the auth
  path: `server.py` first peeks at the token store and, if absent, fails
  fast with FR-007 messaging — it never instantiates a client that could
  trigger an implicit browser flow (FR-001).
- **Alternatives considered**:
  - Local HTTPS callback listener (start a server on the callback port) —
    rejected: violates the constitution's "no inbound network sockets"
    constraint for a stdio server, adds self-signed-cert browser warnings,
    port-conflict edge cases, and more code (violates KISS). The
    paste-the-URL flow is schwabdev's default and needs zero sockets.
  - Manual flow that only prints the URL without opening the browser —
    rejected as primary (worse UX for SC-001); kept as automatic fallback
    if `webbrowser.open` fails (schwabdev already logs this path).

## R3. Silent reuse and automatic refresh (US2)

- **Decision**: On every `serve` start, verify the token store exists, then
  instantiate `schwabdev.Client`, which loads tokens from its SQLite DB and
  calls `update_tokens()` at init; thereafter each request path calls
  `client.update_tokens()` (schwabdev refreshes the access token when
  < 61 s remain). Our server additionally runs one explicit
  `linked_accounts()` read proactively before signaling ready (FR-013).
- **Rationale (source-verified)**: schwabdev v4 already implements
  automatic refresh with cross-instance coordination (SQLite
  `BEGIN EXCLUSIVE` + re-load check), so re-implementing refresh would
  violate DRY/III. Thresholds are Schwab-fixed: access token 30 min,
  refresh token 7 days; schwabdev triggers a full browser re-auth via our
  `call_on_auth` hook when the refresh token has < ~60.5 min left — our
  hook converts that into the FR-007 "re-authorization required" path when
  it happens in `serve` context (non-interactive), and into the normal
  interactive flow only in `auth` context. Spec SC-002's "10 consecutive
  sessions without manual login" holds inside the 7-day refresh window.
- **Alternatives considered**:
  - Background refresh thread in our code — rejected (YAGNI); schwabdev
    refreshes on-demand per request and at init, which satisfies the spec.
  - Proactive validation via `preferences()` instead of
    `linked_accounts()` — either works; `linked_accounts()` chosen: it is
    the documented first call for any account access and returns a tiny
    payload.

## R4. Token storage location, format, and permissions (FR-003, FR-012)

- **Decision**: schwabdev's SQLite token DB at a configurable path
  (`tokens_db` parameter), default `~/.schwab-mcp/tokens.db` (distinct from
  schwabdev's own `~/.schwabdev/tokens.db` so this project owns its
  store). After any write, we enforce `0o600` on the file and `0o700` on
  its directory. No encryption at rest (owner decision 2026-10-19, KISS).
- **Rationale**: The spec requires a local file outside the repo with
  owner-only restrictive permissions and configurable location. A SQLite
  single-row DB is a plain file on disk; schwabdev owns its schema
  (DRY), and we only need to know "row present or not" (peek) plus file
  permissions. `chmod 600` satisfies "readable only by the owner" without
  adding an encryption dependency.
- **Alternatives considered**:
  - Fernet encryption of the token DB (schwabdev supports it via an
    `encryption` key) — rejected: owner explicitly chose simplicity over
    encryption-at-rest; key management would add config surface for no
    real gain on a single-owner machine.
  - JSON token file managed by schwab-py — rejected with library choice.

## R5. Concurrent authorization refusal (FR-011)

- **Decision**: Advisory lock file (e.g. `~/.schwab-mcp/auth.lock`)
  acquired with an exclusive, non-blocking OS lock at the start of `auth`;
  a second concurrent `auth` exits immediately with the FR-007 concurrent
  message. The lock file holds no secrets and is removed on normal exit.
- **Rationale**: The spec forbids a hanging or corrupting second attempt;
  an OS-level advisory lock (`fcntl.flock` on POSIX — the target platforms
  are macOS/Linux) is a few lines, crash-safe (lock dies with the
  process), and cannot corrupt the token store. schwabdev's internal
  SQLite `BEGIN EXCLUSIVE` coordination covers refresh races between
  processes, but not a friendly "you're already authorizing" message —
  our lock adds exactly that.
- **Alternatives considered**:
  - Rely only on schwabdev's DB lock — rejected: a second `auth` would
    proceed to open a browser and prompt simultaneously (confusing, and
    spec FR-011 demands refusal with a clear message).
  - PID-file staleness checks — rejected: more code, worse failure modes
    than a real advisory lock.

## R6. Credentials from environment variables (FR-008)

- **Decision**: Read `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`,
  `SCHWAB_CALLBACK_URL` (optional; default `https://127.0.0.1`, matching
  schwabdev's default and the common portal registration) and
  `SCHWAB_TOKEN_DB` (optional; default `~/.schwab-mcp/tokens.db`) at
  process start; fail fast when required vars are missing/empty. We do not
  re-validate key lengths — schwabdev already raises precise ValueErrors,
  which we map to the FR-007 "invalid config" message (DRY).
- **Rationale**: Spec clarification: env vars, optionally sourced from an
  env file outside the repo (`set -a; source ~/.schwab-mcp/env; set +a`
  documented in quickstart). Fail-fast at startup covers both `auth` and
  `serve`. Avoids duplicating schwabdev's format validation.
- **Alternatives considered**:
  - Config file parsing in-repo — rejected: spec says env vars only;
    an env-file loader would be speculative surface (YAGNI).
  - Full local re-validation of key lengths — rejected: duplicates
    schwabdev validation (violates DRY) and can drift from Schwab's real
    rules.

## R7. Secret redaction and auth event logging (FR-006, FR-014)

- **Decision**: A single `log.py` owning (a) a logging `Filter` installed
  on the root logger and on schwabdev's `"Schwabdev"` logger that scrubs
  any occurrence of known secret values (app key, app secret, and any
  token material we have seen in memory) with `***`, and (b) an
  `auth_event(event, outcome)` emitter that writes timestamped,
  secret-free entries for: authorization start, authorization
  success/failure, renewal success/failure. Events go to stderr (server is
  stdio — stdout is the MCP channel; logs must never touch stdout).
- **Rationale**: FR-006 demands verifiable zero leakage; a defense-in-depth
  filter is testable (unit tests assert redaction of every known secret)
  even though the normal code paths never log secrets. Schwabdev logs
  response bodies on token-endpoint errors via its own logger — installing
  our filter on its logger keeps that from ever leaking material. Logging
  to stderr keeps the MCP stdio channel clean by construction.
- **Alternatives considered**:
  - Audit-only approach (review logs by hand) — rejected: FR-006 requires
    automated verifiability (SC-003).
  - Log file — rejected (YAGNI): stderr is capturable and keeps state
    minimal; the spec only requires a local event record, which stderr
    events satisfy and can later be redirected by the owner.

## R8. Failure-mode taxonomy and mapping (FR-007, FR-009, US3)

- **Decision**: `errors.py` defines one `AuthError` hierarchy with exactly
  one subclass per spec failure mode — `MissingConfigError`,
  `InvalidConfigError`, `AuthorizationCancelledError`,
  `TokenStoreCorruptedError`, `ReauthorizationRequiredError`,
  `ConcurrentAuthError`, `ConnectivityError` — each carrying its fixed,
  actionable message (and exit codes for the CLI). Mapping points:
  schwabdev `ValueError` (config) → InvalidConfigError; token-store peek
  parse/decrypt failure → TokenStoreCorruptedError (store treated as
  absent per FR-009, message points to `schwab-mcp auth`); refresh-token
  expiry/rejection → ReauthorizationRequiredError; browser flow aborted
  (empty paste / declined) → AuthorizationCancelledError; network failure
  during refresh with one retry → ConnectivityError.
- **Rationale**: The spec requires a *distinct, actionable* message per
  failure mode with no raw tracebacks and no hanging; a closed taxonomy
  makes SC-005 (one-by-one verification) mechanical and gives tests a
  single seam to assert against.
- **Alternatives considered**:
  - Reuse schwabdev's logged error strings directly — rejected: they are
    library-internal, not user-actionable in our command names, and leak
    internal details (raw traceback risk).
  - Generic single error with codes — rejected: weaker guarantee for
    SC-005, more branching at call sites.

## R9. MCP server startup and ready semantics (FR-013, SC-004)

- **Decision**: `server.py` boots with the official `mcp` Python SDK
  (FastMCP, stdio transport). Sequence: load/validate config → peek token
  store → if absent/corrupt → emit FR-007 message and exit nonzero (before
  any MCP handshake) → instantiate client (auto-refresh if needed) → run
  one proactive `linked_accounts()` read → only then connect stdio and
  signal ready. No account tools registered in this feature (next feature).
- **Rationale**: The clarified requirement is proactive validation *before*
  ready; doing it before the stdio handshake guarantees an invalid token
  never reaches a client session. FastMCP is the official SDK (Principle
  III); stdio-only matches the constitution. SC-004's 5 s budget is
  asserted by a performance test with a stubbed Schwab API.
- **Alternatives considered**:
  - Validate lazily at first tool call — rejected by explicit spec
    clarification (proactive at startup).
  - Custom raw-JSON MCP framing — rejected: duplicates the official SDK.

## R10. Test/tooling setup

- **Decision**: `pyproject.toml` (PEP 621) with `uv` for dependency and
  environment management; `pytest` (+`pytest-asyncio` if the SDK layer
  needs it); console script `schwab-mcp = schwab_mcp.cli:main`. Tests hit
  a stubbed schwabdev client (real HTTP only in the owner-run quickstart).
- **Rationale**: Local toolchain already has `uv` and Python 3.14;
  schwabdev requires >=3.11. TDD (constitution I) needs fast, hermetic
  tests — stubbing the Schwab API keeps the suite green without network
  or credentials.
- **Alternatives considered**:
  - pip + requirements.txt — rejected: uv is installed, faster, and
    lockfile-driven.
  - Live-API integration tests in CI — rejected: credentials can never be
    in CI; live validation belongs to the owner-run quickstart.

## Carried-forward open items

- Owner action (pre-existing from assessment): the Schwab developer app
  must be registered/approved before the first real `schwab-mcp auth`.
  Not resolvable by this project.
- ToS full text remains unread (403 on fetch, accepted residual risk at
  decide stage); revisit only on Schwab policy signal changes.
