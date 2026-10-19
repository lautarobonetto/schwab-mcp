"""Configuration loading and validation (T005).

Provides ``load_config()`` which reads required and optional environment
variables and returns a validated ``Config`` instance.  Credentials are
automatically registered with the redaction filter for log scrubbing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import schwab_mcp.log as _log

from schwab_mcp.errors import InvalidConfigError, MissingConfigError


# ---------------------------------------------------------------------------
# Config type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """Application configuration loaded from environment variables."""

    app_key: str
    app_secret: str
    callback_url: str
    token_db: str

    # Bracket-index access so callers can write ``config["app_key"]``
    # without converting to a dict.
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


# ---------------------------------------------------------------------------
# Environment variable names
# ---------------------------------------------------------------------------

_ENV_APP_KEY = "SCHWAB_APP_KEY"
_ENV_APP_SECRET = "SCHWAB_APP_SECRET"
_ENV_CALLBACK_URL = "SCHWAB_CALLBACK_URL"
_ENV_TOKEN_DB = "SCHWAB_TOKEN_DB"

# ---------------------------------------------------------------------------
# Defaults  (FR-012)
# ---------------------------------------------------------------------------

_DEFAULT_CALLBACK_URL = "https://127.0.0.1"
_DEFAULT_TOKEN_DB = "~/.schwab-mcp/tokens.db"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config() -> Config:
    """Load and validate configuration from environment variables.

    Returns
    -------
    Config
        A frozen dataclass with validated configuration values.

    Raises
    ------
    MissingConfigError
        If ``SCHWAB_APP_KEY`` or ``SCHWAB_APP_SECRET`` is missing or
        empty/whitespace-only.
    InvalidConfigError
        If ``SCHWAB_TOKEN_DB`` is set to an invalid path (empty,
        whitespace-only, or ending with ``/``).
    """
    # --- Required: app key -------------------------------------------------
    raw_key = os.environ.get(_ENV_APP_KEY)
    if not raw_key or not raw_key.strip():
        raise MissingConfigError(
            detail=f"{_ENV_APP_KEY} is required but was not set or was empty"
        )

    # --- Required: app secret ----------------------------------------------
    raw_secret = os.environ.get(_ENV_APP_SECRET)
    if not raw_secret or not raw_secret.strip():
        raise MissingConfigError(
            detail=f"{_ENV_APP_SECRET} is required but was not set or was empty"
        )

    app_key = raw_key.strip()
    app_secret = raw_secret.strip()

    # Register credentials with the redaction filter  (FR-006)
    _log.register_secret(app_key)
    _log.register_secret(app_secret)

    # --- Optional: callback URL --------------------------------------------
    raw_callback = os.environ.get(_ENV_CALLBACK_URL)
    callback_url = raw_callback.strip() if raw_callback else _DEFAULT_CALLBACK_URL

    # --- Optional: token DB path -------------------------------------------
    raw_token_db = os.environ.get(_ENV_TOKEN_DB)

    if raw_token_db is not None:
        token_db = raw_token_db.strip()
        if not token_db:
            raise InvalidConfigError(
                detail=f"{_ENV_TOKEN_DB} must not be empty or whitespace-only"
            )
        if token_db.endswith("/"):
            raise InvalidConfigError(
                detail=f"{_ENV_TOKEN_DB} must not end with '/'"
            )
    else:
        token_db = _DEFAULT_TOKEN_DB

    # Expand ``~`` so the path is directly usable by os.stat/os.open/
    # sqlite3 (a literal '~' path crashes the filesystem APIs and the
    # advisory lock — FR-012 sensible local defaults must actually work).
    token_db = os.path.expanduser(token_db)

    return Config(
        app_key=app_key,
        app_secret=app_secret,
        callback_url=callback_url,
        token_db=token_db,
    )