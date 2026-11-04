"""Unit tests for CLI command dispatch (TD-006 — DRY dispatch).

Pins the error-mapping contract the four command arms previously
expressed through duplicated ``try / except / else sys.exit`` blocks in
``schwab_mcp.cli.main``:

- every documented command has a dispatch entry;
- ``AuthError`` maps to its per-class ``exit_code`` with ``message`` on
  stderr;
- unexpected exceptions exit 1 with "Unexpected error" on stderr;
- success exits 0;
- a runner that exits itself (``run_renew`` outcome codes) is not
  intercepted.

References
----------
- .specify/bugs/td-006-registration-cli-dry/assessment.md
"""

from __future__ import annotations

import pytest

from schwab_mcp.errors import (
    AuthorizationCancelledError,
    ConcurrentAuthError,
    MissingConfigError,
)


class TestDispatchTable:
    """Every documented command must have a dispatch entry (TD-006)."""

    def test_dispatch_table_covers_all_commands(self) -> None:
        from schwab_mcp.cli import _COMMAND_RUNNERS

        assert set(_COMMAND_RUNNERS) == {
            "auth",
            "renew",
            "auth-status",
            "serve",
        }


class TestRunCommandErrorMapping:
    """The shared error mapping (formerly duplicated four times)."""

    def test_success_exits_zero(self) -> None:
        from schwab_mcp.cli import _run_command

        with pytest.raises(SystemExit) as excinfo:
            _run_command(lambda: None)
        assert excinfo.value.code == 0

    def test_auth_error_maps_to_exit_code(self, capsys) -> None:
        from schwab_mcp.cli import _run_command

        def runner() -> None:
            raise MissingConfigError()

        with pytest.raises(SystemExit) as excinfo:
            _run_command(runner)
        assert excinfo.value.code == MissingConfigError.exit_code
        assert MissingConfigError.message in capsys.readouterr().err

    def test_unexpected_error_exits_one_with_stderr(self, capsys) -> None:
        from schwab_mcp.cli import _run_command

        def runner() -> None:
            raise RuntimeError("boom")

        with pytest.raises(SystemExit) as excinfo:
            _run_command(runner)
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "Unexpected error" in err
        assert "boom" in err

    def test_runner_self_exit_is_not_intercepted(self) -> None:
        """``run_renew`` exits itself with outcome-specific codes; the
        wrapper must let ``SystemExit`` propagate untouched."""
        from schwab_mcp.cli import _run_command

        def runner() -> None:
            raise SystemExit(7)

        with pytest.raises(SystemExit) as excinfo:
            _run_command(runner)
        assert excinfo.value.code == 7


class TestAuthCommandSpecialHandling:
    """The auth arm keeps its distinct exception handling (assessment:
    it has no generic ``except Exception`` and audits concurrent-auth
    refusals)."""

    def test_concurrent_auth_maps_to_its_exit_code(self) -> None:
        from schwab_mcp.cli import _run_auth_command

        def runner() -> None:
            raise ConcurrentAuthError()

        with pytest.raises(SystemExit) as excinfo:
            _run_auth_command(runner)
        assert excinfo.value.code == ConcurrentAuthError.exit_code

    def test_cancelled_auth_maps_to_its_exit_code(self) -> None:
        from schwab_mcp.cli import _run_auth_command

        def runner() -> None:
            raise AuthorizationCancelledError()

        with pytest.raises(SystemExit) as excinfo:
            _run_auth_command(runner)
        assert excinfo.value.code == AuthorizationCancelledError.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
