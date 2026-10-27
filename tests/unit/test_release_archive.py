"""Archive assembly — exact allowlist set, deterministic output (FR-002, FR-011).

Task T012 (US1): assembly emits exactly the allowlist member set, wrapped
under the single top-level directory ``schwab-mcp-<version>/``, with
normalized member timestamps and fixed member order; two consecutive
assemblies are byte-equivalent.
"""

from __future__ import annotations

import hashlib
import zipfile

import pytest

from tests.unit.helpers import make_fake_wheel, make_release_project, release_sandbox

from schwab_mcp_release.allowlist import member_specs, source_map, wheel_name, wrap_dir
from schwab_mcp_release.archive import assemble_archive

VERSION = "9.9.9"


def _sources(sandbox, wheel_path):
    return source_map(sandbox, VERSION, wheel_path)


def _assemble(sandbox, wheel_path, out_name="a.zip", build_dirty=False):
    return assemble_archive(
        version=VERSION,
        build_dirty=build_dirty,
        sources=_sources(sandbox, wheel_path),
        out_zip=sandbox / out_name,
    )


@pytest.fixture
def project():
    with release_sandbox("archive") as sandbox:
        make_release_project(sandbox)
        wheel = make_fake_wheel(sandbox / "dist", VERSION)
        yield sandbox, wheel


class TestAssembleArchive:
    def test_emits_exactly_the_allowlist_member_set(self, project) -> None:
        sandbox, wheel = project
        result = _assemble(sandbox, wheel)
        with zipfile.ZipFile(result.archive_path) as zf:
            names = set(zf.namelist())
        expected = {f"{wrap_dir(VERSION)}/{spec.path}" for spec in member_specs(VERSION)}
        assert names == expected

    def test_single_top_level_wrapping_directory(self, project) -> None:
        sandbox, wheel = project
        result = _assemble(sandbox, wheel)
        with zipfile.ZipFile(result.archive_path) as zf:
            tops = {name.split("/")[0] for name in zf.namelist()}
        assert tops == {wrap_dir(VERSION)}

    def test_member_order_is_fixed(self, project) -> None:
        sandbox, wheel = project
        result = _assemble(sandbox, wheel)
        with zipfile.ZipFile(result.archive_path) as zf:
            names = zf.namelist()
        assert names == [f"{wrap_dir(VERSION)}/{spec.path}" for spec in member_specs(VERSION)]

    def test_member_timestamps_are_normalized(self, project) -> None:
        sandbox, wheel = project
        result = _assemble(sandbox, wheel)
        with zipfile.ZipFile(result.archive_path) as zf:
            for info in zf.infolist():
                assert info.date_time == (1980, 1, 1, 0, 0, 0), info.filename

    def test_two_consecutive_assemblies_are_byte_equivalent(self, project) -> None:
        sandbox, wheel = project
        first = _assemble(sandbox, wheel, "first.zip")
        second = _assemble(sandbox, wheel, "second.zip")
        assert first.archive_path.read_bytes() == second.archive_path.read_bytes()
        assert hashlib.sha256(first.archive_path.read_bytes()).hexdigest() == second.sha256

    def test_readme_is_copied_verbatim(self, project) -> None:
        sandbox, wheel = project
        result = _assemble(sandbox, wheel)
        with zipfile.ZipFile(result.archive_path) as zf:
            shipped = zf.read(f"{wrap_dir(VERSION)}/README.md")
        assert shipped == (sandbox / "docs" / "release" / "README.md").read_bytes()

    def test_install_script_ships_executable(self, project) -> None:
        sandbox, wheel = project
        result = _assemble(sandbox, wheel)
        with zipfile.ZipFile(result.archive_path) as zf:
            info = zf.getinfo(f"{wrap_dir(VERSION)}/install.sh")
        assert info.external_attr >> 16 & 0o111, "install.sh must be executable"

    def test_result_reports_content_member_count(self, project) -> None:
        sandbox, wheel = project
        result = _assemble(sandbox, wheel)
        # 7 content members: README, wheel, 4 manuals, install.sh
        assert result.member_count == 7
        assert result.archive_size == result.archive_path.stat().st_size
        assert result.sha256 == hashlib.sha256(result.archive_path.read_bytes()).hexdigest()
