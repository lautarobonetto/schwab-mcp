"""Completeness check — allowlist-driven (FR-008).

Task T014 (US1): the check passes when every required allowlist member is
present in the archive and FAILS naming the missing member exactly like
``MISSING: manuals/installation.md``.  A zero-byte required member counts
as missing.  No additional top-level entry is allowed (archive-layout).
"""

from __future__ import annotations

from tests.unit.helpers import (
    make_fake_wheel,
    make_release_project,
    release_sandbox,
    write_release_zip,
)

from schwab_mcp_release.allowlist import member_specs, source_map
from schwab_mcp_release.checks import check_completeness

VERSION = "9.9.9"


def _complete_members(sandbox, wheel):
    sources = source_map(sandbox, VERSION, wheel)
    return {path: src.read_bytes() for path, src in sources.items()}


class TestCheckCompleteness:
    def test_passes_when_every_required_member_is_present(self) -> None:
        with release_sandbox("checks") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(sandbox / "dist", VERSION)
            members = _complete_members(sandbox, wheel)
            members["manifest.json"] = b"{}"
            members["SHA256SUMS"] = b""
            members["SHA256SUMS"] = b"deadbeef  README.md\n"
            archive = write_release_zip(sandbox / "ok.zip", VERSION, members)
            assert check_completeness(archive, VERSION) == []

    def test_fails_naming_the_missing_member(self) -> None:
        with release_sandbox("checks") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(sandbox / "dist", VERSION)
            members = _complete_members(sandbox, wheel)
            members["manifest.json"] = b"{}"
            members["SHA256SUMS"] = b"x  README.md\n"
            del members["manuals/installation.md"]
            archive = write_release_zip(sandbox / "missing.zip", VERSION, members)
            assert check_completeness(archive, VERSION) == ["MISSING: manuals/installation.md"]

    def test_zero_byte_member_counts_as_missing(self) -> None:
        with release_sandbox("checks") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(sandbox / "dist", VERSION)
            members = _complete_members(sandbox, wheel)
            members["manifest.json"] = b"{}"
            members["SHA256SUMS"] = b"x  README.md\n"
            members["manuals/usage.md"] = b""
            archive = write_release_zip(sandbox / "empty.zip", VERSION, members)
            assert check_completeness(archive, VERSION) == ["MISSING: manuals/usage.md"]

    def test_reports_every_missing_member(self) -> None:
        with release_sandbox("checks") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(sandbox / "dist", VERSION)
            members = _complete_members(sandbox, wheel)
            members["manifest.json"] = b"{}"
            members["SHA256SUMS"] = b"x  README.md\n"
            del members["manuals/usage.md"]
            del members["install.sh"]
            archive = write_release_zip(sandbox / "multi.zip", VERSION, members)
            assert set(check_completeness(archive, VERSION)) == {
                "MISSING: manuals/usage.md",
                "MISSING: install.sh",
            }

    def test_fails_naming_unexpected_member(self) -> None:
        with release_sandbox("checks") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(sandbox / "dist", VERSION)
            members = _complete_members(sandbox, wheel)
            members["manifest.json"] = b"{}"
            members["SHA256SUMS"] = b"x  README.md\n"
            members["NOTES.md"] = b"extra\n"
            archive = write_release_zip(sandbox / "extra.zip", VERSION, members)
            assert check_completeness(archive, VERSION) == ["UNEXPECTED: NOTES.md"]

    def test_member_set_is_the_allowlist(self) -> None:
        """Every allowlist member is required for completeness (DRY: same source)."""
        with release_sandbox("checks") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(sandbox / "dist", VERSION)
            for spec in member_specs(VERSION):
                members = _complete_members(sandbox, wheel)
                members["manifest.json"] = b"{}"
                members["SHA256SUMS"] = b"x  README.md\n"
                del members[spec.path]
                archive = write_release_zip(
                    sandbox / f"drop-{spec.path.replace('/', '_')}.zip", VERSION, members
                )
                assert check_completeness(archive, VERSION) == [f"MISSING: {spec.path}"]
