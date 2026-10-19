"""Schwab MCP error taxonomy (SC-005).

Defines AuthError as a base class for all authentication and authorization
errors, plus 7 concrete subclasses with distinct actionable messages and exit
codes.
"""


class AuthError(Exception):
    """Base class for all authentication and authorization errors."""

    exit_code: int = 1
    message: str = "An authentication error occurred"

    def __init__(self, *, detail=None, message=None):
        msg = message if message is not None else self.message
        if detail:
            msg = f"{msg}: {detail}"
        super().__init__(msg)


class MissingConfigError(AuthError):
    """Missing required configuration values."""

    exit_code = 2
    message = "Set SCHWAB_APP_KEY / SCHWAB_APP_SECRET"


class InvalidConfigError(AuthError):
    """Invalid configuration values."""

    exit_code = 2
    message = "Fix the values in your environment"


class AuthorizationCancelledError(AuthError):
    """User cancelled the authorization flow."""

    exit_code = 3
    message = "Re-run schwab-mcp auth to retry"


class ReauthorizationRequiredError(AuthError):
    """Existing tokens have expired and need re-authorization."""

    exit_code = 4
    message = "Run schwab-mcp auth"


class TokenStoreCorruptedError(AuthError):
    """Token store is corrupted and cannot be read."""

    exit_code = 5
    message = "Store treated as absent; run schwab-mcp auth"


class ConcurrentAuthError(AuthError):
    """Another authorization flow is already in progress."""

    exit_code = 6
    message = "Another authorization is already running; wait"


class ConnectivityError(AuthError):
    """Network connectivity failure during authorization."""

    exit_code = 7
    message = "Check connectivity; stored tokens not modified"