"""Wheel build — reuses the existing toolchain (research D2).

Task T011 (US1, FR-003): ``build_wheel`` invokes ``uv build --wheel`` and
the produced wheel contains ONLY the ``schwab_mcp`` runtime package — no
``schwab_mcp_release``, no tests, no docs.  Wheel contents are verified by
opening the wheel zip right here in the test.
"""

from __future__ import annotations

import zipfile

import pytest

from tests.unit.helpers import REPO_ROOT, make_release_project, release_sandbox

from schwab_mcp_release.version import resolve_version
from schwab_mcp_release.wheel import WheelBuild, WheelBuildError, build_wheel


class TestBuildWheel:
    def test_invokes_uv_build_and_produces_the_expected_wheel(self) -> None:
        version = resolve_version(REPO_ROOT)
        with release_sandbox("wheel") as out_dir:
            built = build_wheel(REPO_ROOT, out_dir)
            assert isinstance(built, WheelBuild)
            assert built.name == f"schwab_mcp-{version}-py3-none-any.whl"
            assert built.path.is_file()

    def test_wheel_contains_only_the_schwab_mcp_package(self) -> None:
        version = resolve_version(REPO_ROOT)
        with release_sandbox("wheel") as out_dir:
            built = build_wheel(REPO_ROOT, out_dir)
            with zipfile.ZipFile(built.path) as zf:
                names = zf.namelist()
            dist_info = f"schwab_mcp-{version}.dist-info"
            for name in names:
                assert name.startswith(("schwab_mcp/", f"{dist_info}/")), name
            assert not any("schwab_mcp_release" in name for name in names)
            assert not any(
                name.startswith(("tests/", "docs/", "specs/", "plans/", "src/")) for name in names
            )
            tops = {name.split("/")[0] for name in names}
            assert tops == {"schwab_mcp", dist_info}

    def test_wheel_failure_raises_wheel_build_error(self) -> None:
        with release_sandbox("wheel") as sandbox:
            make_release_project(sandbox)
            # Unbuildable backend: uv cannot import it, so the toolchain fails.
            (sandbox / "pyproject.toml").write_text(
                '[project]\nname = "schwab-mcp"\nversion = "9.9.9"\n'
                'requires-python = ">=3.11"\n'
                '[build-system]\nrequires = []\nbuild-backend = "missing_backend_module"\n'
            )
            with pytest.raises(WheelBuildError):
                build_wheel(sandbox, sandbox / "out")


class TestWheelDeterminism:
    """FR-011: same version + inputs -> byte-equivalent artifacts.

    The wheel bytes feed the archive, so the wheel's zip metadata must be
    normalized too — otherwise build-time timestamps leak into the
    archive digest and reproducibility breaks end to end.
    """

    def test_wheel_entries_have_normalized_timestamps(self) -> None:
        with release_sandbox("wheel") as out_dir:
            built = build_wheel(REPO_ROOT, out_dir)
            with zipfile.ZipFile(built.path) as zf:
                for info in zf.infolist():
                    assert info.date_time == (1980, 1, 1, 0, 0, 0), info.filename

    def test_two_wheel_builds_are_byte_equivalent(self) -> None:
        with release_sandbox("wheel") as first, release_sandbox("wheel") as second:
            a = build_wheel(REPO_ROOT, first)
            b = build_wheel(REPO_ROOT, second)
            assert a.path.read_bytes() == b.path.read_bytes()
