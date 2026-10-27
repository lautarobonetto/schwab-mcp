"""Archive allowlist — the single source of truth of shipped members.

Task T006 (FR-002, FR-008, research D5): the allowlist module exposes the
exact member set of ``contracts/archive-layout.md`` — every path under the
wrapping top-level directory ``schwab-mcp-<version>/`` — with a required
flag per member, the verbatim source of each member, and the
forbidden-content rules (dev-material paths + secret-bearing names).
"""

from __future__ import annotations

import pytest

from tests.unit.helpers import make_release_project, release_sandbox

from schwab_mcp_release.allowlist import (
    FORBIDDEN_NAME_PATTERNS,
    FORBIDDEN_PATH_PATTERNS,
    SECRET_CONTENT_PATTERNS,
    content_members,
    member_specs,
    source_map,
    wheel_name,
    wrap_dir,
)

VERSION = "1.2.3"

EXPECTED_MEMBERS = {
    "README.md",
    f"dist/{wheel_name(VERSION)}",
    "manuals/installation.md",
    "manuals/first-run-authentication.md",
    "manuals/usage.md",
    "manuals/troubleshooting.md",
    "install.sh",
    "manifest.json",
    "SHA256SUMS",
}


class TestMemberSet:
    """The exact member set of contracts/archive-layout.md."""

    def test_wrapping_top_level_directory(self) -> None:
        assert wrap_dir(VERSION) == "schwab-mcp-1.2.3"

    def test_wheel_path_pattern(self) -> None:
        assert wheel_name(VERSION) == "schwab_mcp-1.2.3-py3-none-any.whl"

    def test_member_paths_are_exactly_the_contract_set(self) -> None:
        assert {spec.path for spec in member_specs(VERSION)} == EXPECTED_MEMBERS

    def test_every_member_is_required(self) -> None:
        for spec in member_specs(VERSION):
            assert spec.required is True, spec.path

    def test_content_members_exclude_generated_inventory(self) -> None:
        """``manifest.json``/``SHA256SUMS`` are the inventory artifacts
        themselves (self-reference) and are not content members."""
        paths = {spec.path for spec in content_members(VERSION)}
        assert paths == EXPECTED_MEMBERS - {"manifest.json", "SHA256SUMS"}

    def test_member_order_is_fixed(self) -> None:
        """Members are assembled in a deterministic, fixed order (FR-011)."""
        paths = [spec.path for spec in member_specs(VERSION)]
        assert paths == [
            "README.md",
            f"dist/{wheel_name(VERSION)}",
            "manuals/installation.md",
            "manuals/first-run-authentication.md",
            "manuals/usage.md",
            "manuals/troubleshooting.md",
            "install.sh",
            "manifest.json",
            "SHA256SUMS",
        ]


class TestSources:
    """Where each content member comes from on the maintainer's disk."""

    def test_readme_is_the_verbatim_docs_release_copy(self) -> None:
        with release_sandbox("allowlist") as sandbox:
            make_release_project(sandbox)
            sources = source_map(sandbox, VERSION, sandbox / "dist" / wheel_name(VERSION))
            assert sources["README.md"] == sandbox / "docs" / "release" / "README.md"

    def test_manuals_come_from_docs_release(self) -> None:
        with release_sandbox("allowlist") as sandbox:
            make_release_project(sandbox)
            sources = source_map(sandbox, VERSION, sandbox / "dist" / wheel_name(VERSION))
            for manual in ("installation", "first-run-authentication", "usage", "troubleshooting"):
                assert sources[f"manuals/{manual}.md"] == sandbox / "docs" / "release" / f"{manual}.md"

    def test_install_script_source(self) -> None:
        with release_sandbox("allowlist") as sandbox:
            make_release_project(sandbox)
            sources = source_map(sandbox, VERSION, sandbox / "dist" / wheel_name(VERSION))
            assert sources["install.sh"] == sandbox / "src" / "schwab_mcp_release" / "install.sh"

    def test_wheel_source_is_the_built_wheel(self) -> None:
        with release_sandbox("allowlist") as sandbox:
            make_release_project(sandbox)
            wheel = sandbox / "dist" / wheel_name(VERSION)
            sources = source_map(sandbox, VERSION, wheel)
            assert sources[f"dist/{wheel_name(VERSION)}"] == wheel


class TestForbiddenContentRules:
    """Dev-material + secret rules quoted from contracts/archive-layout.md."""

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
        ],
    )
    def test_dev_material_paths_are_forbidden(self, path: str) -> None:
        assert any(p.search(path) for p in FORBIDDEN_PATH_PATTERNS), path

    @pytest.mark.parametrize(
        "path",
        [
            "README.md",
            f"dist/{wheel_name(VERSION)}",
            "manuals/installation.md",
            "manuals/first-run-authentication.md",
            "manuals/usage.md",
            "manuals/troubleshooting.md",
            "install.sh",
            "manifest.json",
            "SHA256SUMS",
        ],
    )
    def test_allowlist_members_are_not_dev_material(self, path: str) -> None:
        assert not any(p.search(path) for p in FORBIDDEN_PATH_PATTERNS), path

    @pytest.mark.parametrize(
        "name",
        [".env", ".env.local", "server.pem", "tokens.db", "client_secrets.json", "credentials.txt"],
    )
    def test_secret_bearing_names_are_forbidden(self, name: str) -> None:
        assert any(p.search(name) for p in FORBIDDEN_NAME_PATTERNS), name

    @pytest.mark.parametrize(
        "content",
        [
            'api_key = "1234567890abcdef"\n',
            "app_key='abcdef1234567890'\n",
            'client_secret = "s3cr3t-value-here"\n',
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9xxxx\n",
            "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADAN\n",
        ],
    )
    def test_credential_shaped_content_is_forbidden(self, content: str) -> None:
        assert any(p.search(content) for p in SECRET_CONTENT_PATTERNS), content

    @pytest.mark.parametrize(
        "content",
        [
            "Set the Schwab app key and secret in your environment before running auth.\n",
            "Your credentials are stored only in ~/.schwab-mcp/tokens.db on your machine.\n",
            "run: schwab-mcp auth to retry\n",
            '{"version": "1.2.3", "build_dirty": false}\n',
        ],
    )
    def test_benign_manual_text_is_not_flagged(self, content: str) -> None:
        assert not any(p.search(content) for p in SECRET_CONTENT_PATTERNS), content
