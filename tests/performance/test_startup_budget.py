"""Performance test: startup-validation budget (SC-004).

Asserts that the ``schwab-mcp serve`` startup sequence — config load → peek
store → client init → proactive read → ready — completes in under 5 seconds
wall-clock time.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Fake schwabdev Client — mirrors the subset that ``run_serve()`` uses
# ---------------------------------------------------------------------------


class FakeSchwabdevClient:
    """A stubbed schwabdev Client whose methods never touch the network.

    ``run_serve()`` constructs this via ``schwabdev.Client(...)`` and calls
    ``linked_accounts()`` through ``retry_once()``.
    """

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        callback_url: str,
        tokens_db: str | Path,
        call_on_auth: Any = None,
        open_browser_for_auth: bool = False,
        **kwargs: Any,
    ) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.callback_url = callback_url
        self.tokens_db = str(tokens_db)
        self.call_on_auth = call_on_auth
        self.open_browser_for_auth = open_browser_for_auth

    def linked_accounts(self) -> dict[str, Any]:
        """Return a minimal fake response (no network I/O)."""
        return {"accounts": [{"accountNumber": "12345678", "type": "MARGIN"}]}


# ---------------------------------------------------------------------------
# Fake MCPServer — returns immediately instead of blocking on stdio
# ---------------------------------------------------------------------------


class FakeMCPServer:
    """Non-blocking stand-in for ``mcp.server.MCPServer``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def add_tool(self, fn: Any, name: str = "", description: str = "") -> None:
        """Register a tool (stub — no-op for performance test)."""
        pass

    async def run_stdio_async(self) -> None:
        """No-op; returns immediately instead of blocking on stdio."""
        return


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token_db(path: Path) -> Path:
    """Create a valid schwabdev SQLite token store at *path*.

    The schema matches what the real schwabdev library creates:
    a ``schwabdev`` table with a single populated row.
    """
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
            (
                "fake-access-token",
                "fake-refresh-token",
                "fake-id-token",
                "2026-10-19T12:00:00Z",
                "2026-10-19T12:00:00Z",
                1800,
                "Bearer",
                "readonly",
            ),
        )
        con.commit()
    finally:
        con.close()
    return path


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


class TestStartupBudget:
    """Assert the startup-validation sequence completes within SC-004 budget."""

    @pytest.mark.performance
    def test_startup_completes_under_budget(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The full startup-validation sequence must complete in < 5.0 s."""
        # ---- Arrange ----------------------------------------------------------
        # Valid credentials
        monkeypatch.setenv("SCHWAB_APP_KEY", "TEST_APP_KEY_32CHARS__FILLER")
        monkeypatch.setenv("SCHWAB_APP_SECRET", "TEST_APP_SECRET_32CHAR_FILLER")
        monkeypatch.setenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1")

        # Valid, pre-populated token store
        token_db = _make_token_db(tmp_path / "tokens.db")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", str(token_db))

        # Stub the schwabdev client (inject before ``run_serve()`` does its
        # local ``import schwabdev``)
        monkeypatch.setattr("schwabdev.Client", FakeSchwabdevClient)

        # Stub the MCP server so ``run_stdio_async()`` returns immediately
        monkeypatch.setattr(
            "schwab_mcp.server.MCPServer", FakeMCPServer
        )

        # Import after monkeypatches are in place
        from schwab_mcp.server import run_serve

        # ---- Act --------------------------------------------------------------
        start = time.perf_counter()
        run_serve()
        elapsed = time.perf_counter() - start

        # ---- Assert -----------------------------------------------------------
        assert elapsed < 5.0, (
            f"Startup-validation took {elapsed:.3f}s, "
            f"expected < 5.0s (SC-004)"
        )