"""Token store peek, permission enforcement, advisory auth lock, and retry (FR-003, FR-009, FR-011, T020)."""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from schwab_mcp.errors import ConcurrentAuthError, ConnectivityError

_logger = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., Any])


def parse_issued_datetime(value: object) -> Optional[datetime]:
    """Strictly parse a stored ``*_token_issued`` value as ISO-8601 text.

    This is the **loader contract**: the only real consumer of the store
    (schwabdev's ``Tokens._parse_dt`` during ``Client.__init__``) requires
    the value to be ISO-8601 text and parses it unguarded.  Naive values
    are treated as UTC, mirroring the library.

    Bug store-unparseable-timestamps: numeric epochs (whether REAL or
    numeric TEXT) are **not** accepted here — the real client cannot load
    such a row, so a store holding them must be classified corrupted at
    the peek instead of crashing inside client construction.

    Returns the parsed timezone-aware datetime, or ``None`` when the value
    is not ISO-parseable text.
    """
    if isinstance(value, bool) or not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def issued_to_epoch(value: object, *, strict: bool = False) -> Optional[float]:
    """Convert a stored ``*_token_issued`` value to epoch seconds.

    With ``strict=False`` (the lenient lifetime-reader criterion) numeric
    epoch values are accepted for backward compatibility.  With
    ``strict=True`` only ISO-parseable text is accepted (the loader
    contract — see :func:`parse_issued_datetime`).

    Returns ``None`` when the value does not satisfy the requested
    criterion.
    """
    if isinstance(value, bool) or value is None:
        return None
    if not strict and isinstance(value, (int, float)):
        return float(value)
    parsed = parse_issued_datetime(value)
    return parsed.timestamp() if parsed is not None else None


def _read_schwabdev_row(
    path: str | os.PathLike,
) -> tuple[str, Optional[tuple]]:
    """Open the token store read-only and fetch the ``schwabdev`` row.

    Single implementation of the store-read contract (TD-003):
    ``os.stat`` → empty-file check → read-only SQLite connect →
    query → ``finally: close()``.  Consumed by :func:`peek_store_status`
    and ``renewal.read_store_lifetime`` — do not copy this block.

    Returns
    -------
    (status, row)
        ``("absent", None)``
            The file does not exist, is empty, or the ``schwabdev``
            table exists but holds no rows.
        ``("corrupted", None)``
            ``os.stat`` failed with ``OSError``/``ValueError``, the
            file is not a valid SQLite database, or the schema does
            not match the expected query (FR-009 — no crash).
        ``("present", row)``
            A ``schwabdev`` row was fetched; *row* is the raw tuple in
            query-column order
            ``(expires_in, access_token_issued, refresh_token_issued)``.
    """
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return "absent", None
    except (OSError, ValueError):
        return "corrupted", None

    if st.st_size == 0:
        return "absent", None

    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return "corrupted", None

    try:
        row = con.execute(
            "SELECT expires_in, access_token_issued, refresh_token_issued "
            "FROM schwabdev LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        # Missing/mismatched schema — the loader could not read the row.
        return "corrupted", None
    finally:
        con.close()

    if row is None:
        return "absent", None
    return "present", row


def peek_store_status(path: str | os.PathLike) -> str:
    """Return a tri-state status for a token store.

    Returns
    -------
    ``"present"``
        The store is a valid SQLite file with a **schwabdev** table row
        whose ``*_token_issued`` values are ISO-parseable text (the
        loader contract — the row can actually be loaded by schwabdev).
    ``"absent"``
        The file does not exist or is empty (treat as absent).
    ``"corrupted"``
        The file exists but is not a valid SQLite database, lacks the
        expected schema, or holds a row the loader cannot parse
        (FR-009 — no crash).

    Bug store-unparseable-timestamps: structural validity alone is not
    enough.  schwabdev parses ``access_token_issued`` /
    ``refresh_token_issued`` as ISO-8601 text during ``Client.__init__``
    and raises an unclassifiable error otherwise, so a row with
    non-ISO-parseable timestamps is classified corrupted here — *before*
    any client construction — and every CLI flow recovers through the
    existing corrupted-store paths (renew exit 3, serve exit 5, auth
    quarantine).
    """
    status, row = _read_schwabdev_row(path)
    if status != "present" or row is None:
        return status

    _expires_in, access_issued, refresh_issued = row
    if (
        parse_issued_datetime(access_issued) is None
        or parse_issued_datetime(refresh_issued) is None
    ):
        return "corrupted"
    return "present"


def _backup_timestamp() -> str:
    """UTC timestamp component for backup file names (patchable in tests)."""
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def backup_token_store(path: str | os.PathLike) -> Optional[Path]:
    """Move a *present* token store aside to a timestamped sibling backup.

    Bug auth-false-success: ``auth`` must never trust the rows already in
    the store (a refresh token revoked server-side is indistinguishable
    from a fresh one to any store read).  Renaming the store away
    forces the client's empty-store authorization flow; the caller keeps
    *backup* around and either restores it on failure
    (:func:`restore_token_store`) or discards it on success
    (:func:`discard_token_store_backup`).

    Returns the backup :class:`~pathlib.Path`, or ``None`` when the store
    is absent, empty, or corrupted (never touches those files).
    """
    if peek_store_status(path) != "present":
        return None
    src = Path(path)
    stamp = _backup_timestamp()
    backup = src.with_name(f"{src.name}.bak.{stamp}")
    counter = 1
    while backup.exists():  # never overwrite an existing backup
        backup = src.with_name(f"{src.name}.bak.{stamp}-{counter}")
        counter += 1
    os.rename(src, backup)
    # The backup holds live tokens — owner read/write only (FR-003).
    os.chmod(backup, 0o600)
    # Sidecars at the original name belong to the moved inode; drop them
    # so they cannot shadow the fresh DB written at that path next.
    _drop_sidecars(src)
    return backup


def restore_token_store(
    backup_path: str | os.PathLike | None, store_path: str | os.PathLike
) -> None:
    """Restore *backup_path* over *store_path* (failure path, FR-010).

    ``os.replace`` is atomic and preserves the backup's ``0o600`` mode.
    A ``None`` or already-consumed backup is a no-op.
    """
    if backup_path is None:
        return
    backup = Path(backup_path)
    if not backup.exists():
        return
    os.replace(backup, store_path)
    # Sidecars at the store path belong to the replaced (partial/foreign)
    # DB — drop them so the restored store is never shadowed by a hot
    # journal (bug auth-corrupt-store-blocked).
    _drop_sidecars(Path(store_path))


def discard_token_store_backup(backup_path: str | os.PathLike | None) -> None:
    """Remove the backup after a successful fresh authorization."""
    if backup_path is None:
        return
    with contextlib.suppress(FileNotFoundError):
        os.unlink(backup_path)


_SQLITE_SIDECAR_SUFFIXES = ("-journal", "-wal", "-shm")


def _sidecar_paths(store: Path) -> list[Path]:
    """SQLite sidecar files (hot journal / WAL) belonging to *store*."""
    return [
        store.with_name(f"{store.name}{suffix}")
        for suffix in _SQLITE_SIDECAR_SUFFIXES
    ]


def _drop_sidecars(store: Path) -> None:
    """Remove stray sidecars at *store*'s name (bug auth-corrupt-store-blocked).

    Sidecars belong to a specific database inode.  After the store file is
    renamed or replaced, any sidecar left at the original name is foreign
    — a hot journal that makes SQLite refuse to read whatever file now
    lives at that path (read-only mode cannot recover it)."""
    for sidecar in _sidecar_paths(store):
        with contextlib.suppress(FileNotFoundError):
            os.unlink(sidecar)


def quarantine_corrupt_store(path: str | os.PathLike) -> Optional[Path]:
    """Move a *corrupted* store (and its stray sidecars) aside for forensics.

    Bug auth-corrupt-store-blocked: a corrupted store used to make
    ``auth`` exit 5 with a message telling the user to re-run ``auth`` —
    the same command that kept failing.  Quarantining honors FR-009
    ("treated as absent") without destroying evidence: the file is
    renamed to ``<name>.corrupt.<UTC timestamp>`` with owner-only
    permissions (it may contain token fragments) and any
    ``-journal``/``-wal``/``-shm`` sidecars are removed.

    Returns the quarantine :class:`~pathlib.Path`, or ``None`` when the
    store is not in the corrupted state (present/absent are untouched).
    """
    if peek_store_status(path) != "corrupted":
        return None
    src = Path(path)
    stamp = _backup_timestamp()
    target = src.with_name(f"{src.name}.corrupt.{stamp}")
    counter = 1
    while target.exists():  # never overwrite an existing quarantine
        target = src.with_name(f"{src.name}.corrupt.{stamp}-{counter}")
        counter += 1
    os.rename(src, target)
    os.chmod(target, 0o600)
    _drop_sidecars(src)
    return target


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