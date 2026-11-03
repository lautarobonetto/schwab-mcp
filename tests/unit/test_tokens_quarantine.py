"""Token store quarantine helper (bug auth-corrupt-store-blocked).

A corrupted store must not block ``auth`` in a dead-end loop (exit 5
with a message telling the user to re-run the same failing command).
``run_auth`` now quarantines the unusable file — renaming it to
``*.corrupt.<ts>`` (owner-only, content preserved for forensics) and
removing stray SQLite ``-journal``/``-wal``/``-shm`` sidecars — and lets
the fresh flow proceed.  These tests pin the quarantine contract and the
sidecar hygiene of the backup/restore helpers.
"""

from __future__ import annotations

import os
import stat
import sqlite3
from pathlib import Path

import pytest

from schwab_mcp.tokens import (
    backup_token_store,
    peek_store_status,
    quarantine_corrupt_store,
    restore_token_store,
)


def _make_corrupt_store(path: Path, content: str = "not a database") -> str:
    path.write_text(content)
    return content


def _make_valid_store(path: Path) -> None:
    """Create a store the real loader can load: full schwabdev schema with
    ISO-8601 issued timestamps (the loader contract — bug
    store-unparseable-timestamps)."""
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
            "INSERT INTO schwabdev VALUES "
            "('a', 'r', 'i', '2026-11-03T00:00:00+00:00', "
            "'2026-11-03T00:00:00+00:00', 1800, 'Bearer', 'scope')"
        )
        con.commit()
    finally:
        con.close()


def _make_sidecars(path: Path) -> list[Path]:
    """Create junk SQLite sidecar files for *path* (hot-journal simulation)."""
    sidecars = [
        path.with_name(path.name + suffix)
        for suffix in ("-journal", "-wal", "-shm")
    ]
    for sidecar in sidecars:
        sidecar.write_bytes(b"junk-journal-bytes")
    return sidecars


class TestQuarantineCorruptStore:
    def test_quarantine_moves_corrupt_store_and_drops_sidecars(
        self, tmp_path: Path
    ):
        store = tmp_path / "tokens.db"
        content = _make_corrupt_store(store)
        sidecars = _make_sidecars(store)

        quarantined = quarantine_corrupt_store(store)

        assert quarantined is not None
        assert quarantined.name.startswith("tokens.db.corrupt.")
        assert not store.exists(), "corrupt store must be moved aside"
        assert quarantined.read_text() == content, (
            "quarantine preserves the content for forensics (never deletes)"
        )
        mode = stat.S_IMODE(quarantined.stat().st_mode)
        assert mode == 0o600, "quarantine may contain token fragments"
        for sidecar in sidecars:
            assert not sidecar.exists(), (
                f"stray sidecar {sidecar.name} must not outlive the move"
            )

    def test_quarantine_leaves_present_store_untouched(self, tmp_path: Path):
        store = tmp_path / "tokens.db"
        _make_valid_store(store)

        assert quarantine_corrupt_store(store) is None
        assert store.exists() and peek_store_status(store) == "present"

    def test_quarantine_leaves_absent_store_untouched(self, tmp_path: Path):
        store = tmp_path / "tokens.db"

        assert quarantine_corrupt_store(store) is None
        assert not store.exists()

    def test_quarantine_never_overwrites_an_existing_quarantine(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        def frozen_timestamp() -> str:
            return "20261103T120000Z"

        monkeypatch.setattr(
            "schwab_mcp.tokens._backup_timestamp", frozen_timestamp
        )
        first = tmp_path / "tokens.db"
        _make_corrupt_store(first, "first-corrupt")
        quarantined1 = quarantine_corrupt_store(first)
        assert quarantined1 is not None
        assert quarantined1.name == "tokens.db.corrupt.20261103T120000Z"

        second = tmp_path / "tokens.db"
        _make_corrupt_store(second, "second-corrupt")
        quarantined2 = quarantine_corrupt_store(second)

        assert quarantined2 is not None
        assert quarantined2 != quarantined1, (
            "existing quarantine must never be overwritten"
        )
        assert quarantined1.read_text() == "first-corrupt"
        assert quarantined2.read_text() == "second-corrupt"


class TestSidecarHygiene:
    def test_valid_store_poisoned_by_stray_journal_is_quarantined(
        self, tmp_path: Path
    ):
        """The Server1 mechanism (bug auth-corrupt-store-blocked): a
        valid SQLite store shadowed by a foreign hot journal reads as
        'corrupted' (read-only mode cannot recover it) — auth must
        quarantine it (content preserved) and drop the journal."""
        store = tmp_path / "tokens.db"
        _make_valid_store(store)
        _make_sidecars(store)
        assert peek_store_status(store) == "corrupted", (
            "precondition: hot journal makes the store read as corrupted"
        )
        original_bytes = store.read_bytes()

        quarantined = quarantine_corrupt_store(store)

        assert quarantined is not None
        assert quarantined.read_bytes() == original_bytes, (
            "the (possibly valid!) DB must be preserved by the quarantine"
        )
        assert not store.exists()
        for suffix in ("-journal", "-wal", "-shm"):
            assert not (tmp_path / f"tokens.db{suffix}").exists()

    def test_restore_removes_stray_sidecars_of_the_replaced_file(
        self, tmp_path: Path
    ):
        """An aborted fresh DB leaves a hot journal next to the store path;
        a restored DB must not be shadowed by it."""
        store = tmp_path / "tokens.db"
        _make_valid_store(store)
        backup = backup_token_store(store)
        assert backup is not None

        # Simulate the aborted fresh DB: garbage at the store path + hot journal.
        store.write_bytes(b"partial fresh db garbage")
        _make_sidecars(store)

        restore_token_store(backup, store)

        assert peek_store_status(store) == "present", (
            "restored store must be readable — no foreign hot journal"
        )
        for suffix in ("-journal", "-wal", "-shm"):
            assert not (tmp_path / f"tokens.db{suffix}").exists()