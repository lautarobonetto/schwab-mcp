"""Version resolution — ``pyproject.toml`` is the single source of truth.

Task T005 (FR-005, research D4): the release tooling never re-derives or
duplicates the version; it reads exactly ``[project].version`` and fails
explicitly (naming the file) when the file is missing or malformed.
"""

from __future__ import annotations

import tomllib

import pytest

from tests.unit.helpers import REPO_ROOT, make_release_project, release_sandbox

from schwab_mcp_release.version import VersionError, resolve_version


class TestResolveVersion:
    def test_returns_exactly_project_version_from_pyproject(self) -> None:
        expected = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]["version"]
        assert resolve_version(REPO_ROOT) == expected

    def test_reads_version_from_given_project_root(self) -> None:
        with release_sandbox("version") as sandbox:
            make_release_project(sandbox, version="1.2.3")
            assert resolve_version(sandbox) == "1.2.3"

    def test_result_is_the_literal_string_from_the_file(self) -> None:
        with release_sandbox("version") as sandbox:
            make_release_project(sandbox, version="0.0.1rc1")
            assert resolve_version(sandbox) == "0.0.1rc1"


class TestResolveVersionFailures:
    """Failures name the file explicitly — never a generic error (FR-005)."""

    def test_missing_pyproject_names_the_file(self) -> None:
        with release_sandbox("version") as sandbox:
            with pytest.raises(VersionError, match=r"pyproject\.toml"):
                resolve_version(sandbox)

    def test_malformed_pyproject_names_the_file(self) -> None:
        with release_sandbox("version") as sandbox:
            (sandbox / "pyproject.toml").write_text("[project\nversion oops")
            with pytest.raises(VersionError, match=r"pyproject\.toml"):
                resolve_version(sandbox)

    def test_missing_project_version_names_the_file(self) -> None:
        with release_sandbox("version") as sandbox:
            (sandbox / "pyproject.toml").write_text('[project]\nname = "schwab-mcp"\n')
            with pytest.raises(VersionError, match=r"pyproject\.toml"):
                resolve_version(sandbox)
