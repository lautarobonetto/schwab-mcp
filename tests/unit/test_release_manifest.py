"""Manifest + checksums — fields per data-model.md (FR-010).

Task T013 (US1): ``manifest.json`` carries ``version``, ``build_dirty`` and
``members[]`` (path/size/sha256); ``SHA256SUMS`` has one sorted line per
member; the outer ``schwab-mcp-<version>.zip.sha256`` contains
``<sha256>  schwab-mcp-<version>.zip``.

Self-reference rule: ``manifest.json`` and ``SHA256SUMS`` are the
inventory artifacts themselves and therefore describe the *content*
members (README, wheel, 4 manuals, install.sh) — they cannot list their
own hash.  The outer checksum covers the complete archive.
"""

from __future__ import annotations

import hashlib
import json

from tests.unit.helpers import make_release_project, release_sandbox

from schwab_mcp_release.manifest import (
    Member,
    inventory,
    render_manifest,
    render_sha256sums,
    write_outer_checksum,
)

VERSION = "9.9.9"

PAYLOADS = {
    "README.md": b"# readme\n",
    f"dist/schwab_mcp-{VERSION}-py3-none-any.whl": b"wheel-bytes",
    "manuals/installation.md": b"# install\n",
    "manuals/first-run-authentication.md": b"# auth\n",
    "manuals/usage.md": b"# usage\n",
    "manuals/troubleshooting.md": b"# troubleshoot\n",
    "install.sh": b"#!/bin/sh\nexit 0\n",
}


class TestInventory:
    def test_single_pass_hashes_match_stdlib(self) -> None:
        members = inventory(PAYLOADS)
        assert [m.path for m in members] == list(PAYLOADS)
        for member in members:
            data = PAYLOADS[member.path]
            assert member.size == len(data)
            assert member.sha256 == hashlib.sha256(data).hexdigest()


class TestRenderManifest:
    def test_fields_per_data_model(self) -> None:
        members = inventory(PAYLOADS)
        doc = json.loads(render_manifest(VERSION, True, members))
        assert doc["version"] == VERSION
        assert doc["build_dirty"] is True
        assert {m["path"] for m in doc["members"]} == set(PAYLOADS)
        for entry in doc["members"]:
            assert set(entry) == {"path", "size", "sha256"}
            data = PAYLOADS[entry["path"]]
            assert entry["size"] == len(data)
            assert entry["sha256"] == hashlib.sha256(data).hexdigest()

    def test_build_dirty_false_is_recorded(self) -> None:
        doc = json.loads(render_manifest(VERSION, False, inventory(PAYLOADS)))
        assert doc["build_dirty"] is False

    def test_rendering_is_deterministic(self) -> None:
        members = inventory(PAYLOADS)
        assert render_manifest(VERSION, True, members) == render_manifest(VERSION, True, members)


class TestRenderSha256sums:
    def test_one_sorted_line_per_member(self) -> None:
        members = inventory(PAYLOADS)
        lines = render_sha256sums(members).decode().splitlines()
        assert len(lines) == len(PAYLOADS)
        paths = []
        for line in lines:
            digest, path = line.split("  ", 1)
            assert digest == hashlib.sha256(PAYLOADS[path]).hexdigest()
            paths.append(path)
        assert paths == sorted(PAYLOADS)


class TestWriteOuterChecksum:
    def test_line_format_matches_build_command_contract(self) -> None:
        with release_sandbox("manifest") as sandbox:
            archive = sandbox / f"schwab-mcp-{VERSION}.zip"
            archive.write_bytes(b"archive-bytes")
            checksum_path = write_outer_checksum(archive)
            assert checksum_path == sandbox / f"schwab-mcp-{VERSION}.zip.sha256"
            expected = hashlib.sha256(b"archive-bytes").hexdigest()
            assert checksum_path.read_text() == f"{expected}  schwab-mcp-{VERSION}.zip\n"


class TestMember:
    def test_member_is_a_value_object(self) -> None:
        member = Member(path="README.md", size=3, sha256="0" * 64)
        assert member.path == "README.md"
        assert member.size == 3
