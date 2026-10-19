"""Token store peek, permission enforcement, advisory auth lock, and retry (FR-003, FR-009, FR-011, T020)."""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import sqlite3
import time
from typing import Any, Callable, Optional, TypeVar

from schwab_mcp.errors import ConcurrentAuthError, ConnectivityError

_logger = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., Any])


def peek_store(path: str | os.PathLike) -> bool:
    """Check whether a token store exists and has a valid schwabdev token.

    Returns ``True`` when *path* is a SQLite file containing a ``schwabdev``
    table with at least one row.  Returns ``False`` if the file is missing,
    is not valid SQLite, or the table is empty (FR-009 – no crash on
    corrupted content).
    """
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return False

    if st.st_size == 0:
        return False

    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False

    try:
        row = con.execute(
            "SELECT 1 FROM schwabdev LIMIT 1"
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False
    finally:
        con.close()


def peek_store_status(path: str | os.PathLike) -> str:
    """Return a tri-state status for a token store.

    Returns
    -------
    ``"present"``
        The store is a valid SQLite file with a **schwabdev** table row.
    ``"absent"``
        The file does not exist or is empty (treat as absent).
    ``"corrupted"``
        The file exists but is not a valid SQLite database or lacks
        the expected schema (FR-009 — no crash).
    """
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return "absent"
    except (OSError, ValueError):
        return "corrupted"

    if st.st_size == 0:
        return "absent"

    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return "corrupted"

    try:
        row = con.execute(
            "SELECT 1 FROM schwabdev LIMIT 1"
        ).fetchone()
        return "present" if row is not None else "absent"
    except sqlite3.Error:
        return "corrupted"
    finally:
        con.close()


def enforce_permissions(path: str | os.PathLike) -> None:
    """Set restrictive owner-only permissions (FR-003).

    File is set to ``0o600`` (owner read/write) and its parent directory to
    ``0o700`` (owner read/write/execute).  Idempotent.
    """
    os.chmod(path, 0o600)
    parent = os.path.dirname(os.fsdecode(path) if isinstance(path, os.PathLike) else path)
    os.chmod(parent, 0o700)


class AuthLock:
    """Advisory exclusive lock that guards concurrent authorization (FR-011).

    Uses OS-level ``fcntl.flock`` with ``LOCK_EX | LOCK_NB`` against a
    sidecar lock file named ``auth.lock`` placed ALONGSIDE the given path
    (contracts/configuration.md: ``~/.schwab-mcp/auth.lock`` for the default
    token DB — not independently configurable, YAGNI), so that the token
    database itself is never opened or held open.  A second concurrent
    attempt raises
    :exc:`ConcurrentAuthError <schwab_mcp.errors.ConcurrentAuthError>`.
    """

    LOCK_FILE_NAME = "auth.lock"

    def __init__(self, path: str | os.PathLike) -> None:
        resolved = os.fsdecode(path) if isinstance(path, os.PathLike) else path
        parent = os.path.dirname(resolved) or "."
        self._lock_path = os.path.join(parent, self.LOCK_FILE_NAME)
        self._fd: Optional[int] = None

    def __enter__(self) -> AuthLock:
        fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        self._fd = fd
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            os.close(fd)
            self._fd = None
            raise ConcurrentAuthError() from None
        return self

    def __exit__(self, *args: object) -> None:
        if self._fd is not None:
            fd = self._fd
            self._fd = None
            os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            os.remove(self._lock_path)


def retry_call(
    fn: Callable[..., Any],
    retries: int = 2,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Call *fn* with the given arguments, retrying up to *retries* times on failure.

    A short fixed wait (0.5 s) is inserted between retry attempts.

    The token DB is guaranteed **not** to be deleted or rewritten on
    failure (T020).  This function only captures transient network errors;
    the caller is responsible for not passing mutating operations.

    Parameters
    ----------
    fn
        The callable to invoke.
    retries
        Maximum number of retry attempts after the initial call.
        Defaults to 2 (so up to 3 total calls).
    *args, **kwargs
        Forwarded to *fn*.

    Returns
    -------
    The return value of *fn*.

    Raises
    ------
    ConnectivityError
        After all attempts are exhausted.
    """
    attempt = 0
    while True:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            attempt += 1
            if attempt > retries:
                raise ConnectivityError(
                    detail="Schwab API unreachable after retry; "
                    "stored tokens were not modified"
                ) from exc
            _logger.warning("Attempt %d failed; retrying: %s", attempt, exc)
            time.sleep(0.5)


def retry_once(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Retry exactly once (backward-compatible wrapper).

    See :func:`retry_call` for details.
    """
    return retry_call(fn, retries=1, *args, **kwargs)