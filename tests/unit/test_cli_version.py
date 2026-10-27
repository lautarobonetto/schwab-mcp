"""Recipient version visibility in ``schwab-mcp --help`` (FR-005).

Task T022 (US2): the version string is visible in the help output and
equals the ``pyproject.toml`` ``[project]`` version — a recipient must be
able to report exactly what they run.  Regression checks document the
current help behavior (subcommands listed, no command -> help + exit 1).
"""

from __future__ import annotations

import tomllib

import pytest

from tests.unit.helpers import REPO_ROOT

from schwab_mcp.cli import main

EXPECTED_VERSION = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]["version"]


class TestHelpVersionVisibility:
    def test_version_visible_and_matches_pyproject(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert EXPECTED_VERSION in out

    def test_help_lists_every_subcommand(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        for command in ("auth", "renew", "auth-status", "serve"):
            assert command in out

    def test_no_command_prints_help_and_exits_1(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 1
        assert "usage: schwab-mcp" in capsys.readouterr().out
