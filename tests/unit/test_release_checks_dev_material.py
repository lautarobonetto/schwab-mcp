"""Dev-material exclusion scan — build fails naming the member (FR-003, FR-009).

Task T028 (US3): the scan over final archive members detects forbidden
dev content — paths ``tests/``, ``specs/``, ``plans/``, ``__pycache__/``,
``.git*``, ``*.egg-info/``, editable source trees, dev config — and fails
naming the offending member (``DEV-MATERIAL: <path>``), including dev
material hidden inside the shipped wheel.
"""

from __future__ import annotations

import pytest

from tests.unit.helpers import (
    make_fake_wheel,
    make_release_project,
    release_sandbox,
    write_release_zip,
)

from schwab_mcp_release.allowlist import source_map
from schwab_mcp_release.archive import assemble_archive
from schwab_mcp_release.checks import check_dev_material

VERSION = "9.9.9"


def _complete_members(sandbox, wheel):
    sources = source_map(sandbox, VERSION, wheel)
    members = {path: src.read_bytes() for path, src in sources.items()}
    members["manifest.json"] = b"{}"
    members["SHA256SUMS"] = b"x  README.md\n"
    return members


class TestCheckDevMaterial:
    def test_clean_archive_passes(self) -> None:
        with release_sandbox("devscan") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(sandbox / "dist", VERSION)
            archive = write_release_zip(sandbox / "clean.zip", VERSION, _complete_members(sandbox, wheel))
            assert check_dev_material(archive, VERSION) == []

    @pytest.mark.parametrize(
        "path",
        [
            "tests/unit/test_x.py",
            "specs/009-mcp-release-packaging/spec.md",
            "plans/roadmap.md",
            ".gitignore",
            ".git/config",
            "__pycache__/mod.cached",
            "schwab_mcp.egg-info/PKG-INFO",
            "pyproject.toml",
            "src/schwab_mcp_release/cli.py",
        ],
    )
    def test_fails_naming_the_offending_member(self, path: str) -> None:
        with release_sandbox("devscan") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(sandbox / "dist", VERSION)
            members = _complete_members(sandbox, wheel)
            members[path] = b"# dev material\n"
            archive = write_release_zip(sandbox / "dirty.zip", VERSION, members)
            assert check_dev_material(archive, VERSION) == [f"DEV-MATERIAL: {path}"]

    def test_detects_dev_material_hidden_inside_the_wheel(self) -> None:
        with release_sandbox("devscan") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(
                sandbox / "dist", VERSION, extra_entries={"tests/probe.py": b"# probe\n"}
            )
            sources = source_map(sandbox, VERSION, wheel)
            archive = assemble_archive(
                version=VERSION,
                build_dirty=False,
                sources=sources,
                out_zip=sandbox / "whl.zip",
            ).archive_path
            problems = check_dev_material(archive, VERSION)
            assert len(problems) == 1
            assert problems[0].startswith("DEV-MATERIAL: ")
            assert "tests/probe.py" in problems[0]

    def test_reports_every_offending_member(self) -> None:
        with release_sandbox("devscan") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(sandbox / "dist", VERSION)
            members = _complete_members(sandbox, wheel)
            members["tests/a.py"] = b"# a\n"
            members["specs/b.md"] = b"# b\n"
            archive = write_release_zip(sandbox / "multi.zip", VERSION, members)
            assert set(check_dev_material(archive, VERSION)) == {
                "DEV-MATERIAL: tests/a.py",
                "DEV-MATERIAL: specs/b.md",
            }
