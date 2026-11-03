"""Token store backup/restore helpers (bug auth-false-success).

``run_auth`` moves an existing store aside before constructing the
schwabdev client so a fresh authorization flow always runs, and restores
the backup byte-identically when the run fails.  These tests pin the
helper contract: present-only backup, owner-only permissions, collision
safety, and exact restore.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from schwab_mcp.tokens import (
    backup_token_store,
    discard_token_store_backup,
    restore_token_store,
)


def _write_store(path: Path, marker: str = "stale-token-bytes") -> bytes:
    """Create a valid (SQLite) token store whose content embeds *marker*."""
    import sqlite3

    con = sqlite3.connect(str(path))
    try:
        con.execute(
            "CREATE TABLE schwabdev ("
            "  access_token TEXT,"
            "  refresh_token TEXT,"
            "  id_token TEXT,"
            "  access_token_issued TEXT,"
            "  refresh_token_issued TEXT,"
            "  expires_in INTEGER,"
            "  token_type TEXT,"
            "  scope TEXT"
            ")"
        )
        con.execute(
            "INSERT INTO schwabdev VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (marker, marker, marker, "2026-11-03T00:00:00Z",
             "2026-11-03T00:00:00Z", 1800, "Bearer", "readonly"),
        )
        con.commit()
    finally:
        con.close()
    os.chmod(path, 0o644)  # deliberately permissive pre-backup
    return path.read_bytes()


class TestBackupTokenStore:
    def test_backup_moves_present_store_to_timestamped_sibling(
        self, tmp_path: Path
    ):
        store = tmp_path / "tokens.db"
        content = _write_store(store)

        backup = backup_token_store(store)

        assert backup is not None
        assert backup.name.startswith("tokens.db.bak.")
        assert not store.exists(), "original must be moved aside"
        assert backup.read_bytes() == content

    def test_backup_enforces_owner_only_permissions(self, tmp_path: Path):
        store = tmp_path / "tokens.db"
        _write_store(store)

        backup = backup_token_store(store)

        assert backup is not None
        mode = stat.S_IMODE(backup.stat().st_mode)
        assert mode == 0o600, (
            "backup holds live tokens — must be owner read/write only"
        )

    def test_backup_absent_store_returns_none(self, tmp_path: Path):
        assert backup_token_store(tmp_path / "missing.db") is None

    def test_backup_empty_file_returns_none(self, tmp_path: Path):
        store = tmp_path / "tokens.db"
        store.write_bytes(b"")
        assert backup_token_store(store) is None

    def test_backup_corrupted_store_returns_none_and_keeps_file(
        self, tmp_path: Path
    ):
        """A non-SQLite store is 'corrupted', not 'present': run_auth
        rejects it before any backup, and the helper must not touch it."""
        store = tmp_path / "tokens.db"
        content = b"this is not sqlite"
        store.write_bytes(content)

        assert backup_token_store(store) is None
        assert store.exists() and store.read_bytes() == content

    def test_backup_never_overwrites_an_existing_backup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Same timestamp must yield distinct backup names (counter)."""

        def frozen_timestamp() -> str:
            return "20261103T120000Z"

        monkeypatch.setattr(
            "schwab_mcp.tokens._backup_timestamp", frozen_timestamp
        )
        first = tmp_path / "tokens.db"
        first_content = _write_store(first, b"first-store")
        backup1 = backup_token_store(first)
        assert backup1 is not None
        assert backup1.name == "tokens.db.bak.20261103T120000Z"

        second = tmp_path / "tokens.db"
        _write_store(second, "second-store")
        backup2 = backup_token_store(second)

        assert backup2 is not None
        assert backup2 != backup1, "existing backup must not be overwritten"
        assert backup1.read_bytes() == first_content
        assert b"second-store" in backup2.read_bytes()


class TestRestoreTokenStore:
    def test_restore_puts_original_bytes_back(self, tmp_path: Path):
        store = tmp_path / "tokens.db"
        content = _write_store(store)
        backup = backup_token_store(store)
        assert backup is not None

        store.write_bytes(b"partial garbage from a failed flow")
        restore_token_store(backup, store)

        assert store.read_bytes() == content
        assert not backup.exists(), "backup consumed by the restore"

    def test_restore_with_no_backup_is_a_noop(self, tmp_path: Path):
        store = tmp_path / "tokens.db"
        restore_token_store(None, store)  # must not raise
        assert not store.exists()

    def test_restore_missing_backup_file_is_a_noop(self, tmp_path: Path):
        store = tmp_path / "tokens.db"
        restore_token_store(tmp_path / "gone.bak.20261103", store)
        assert not store.exists()

    def test_restored_store_keeps_owner_only_permissions(self, tmp_path: Path):
        store = tmp_path / "tokens.db"
        _write_store(store)
        backup = backup_token_store(store)
        assert backup is not None
        # Simulate a permissive partial rewrite by a failed flow.
        store.write_bytes(b"partial garbage")
        os.chmod(store, 0o644)

        restore_token_store(backup, store)

        assert store.read_bytes() != b"partial garbage"
        mode = stat.S_IMODE(store.stat().st_mode)
        assert mode == 0o600


class TestDiscardTokenStoreBackup:
    def test_discard_removes_the_backup(self, tmp_path: Path):
        store = tmp_path / "tokens.db"
        _write_store(store)
        backup = backup_token_store(store)
        assert backup is not None

        discard_token_store_backup(backup)

        assert not backup.exists()

    def test_discard_missing_backup_is_a_noop(self, tmp_path: Path):
        discard_token_store_backup(tmp_path / "nope.bak.20261103")
        discard_token_store_backup(None)  # must not raise