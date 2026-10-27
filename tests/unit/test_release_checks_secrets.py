"""Secret scan — build fails naming the member, never its content (FR-004).

Task T029 (US3): the scan detects secret-bearing members (``.env``,
``*.pem``, ``*token*db*``, ``*secret*``, ``*credential*`` names;
credential-shaped content patterns in text members) and fails naming the
member ONLY — the matched content never appears in the failure output
(credential safety).
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
from schwab_mcp_release.checks import check_secrets

VERSION = "9.9.9"
SECRET_LITERAL = "1234567890abcdef"


def _complete_members(sandbox, wheel):
    sources = source_map(sandbox, VERSION, wheel)
    members = {path: src.read_bytes() for path, src in sources.items()}
    members["manifest.json"] = b"{}"
    members["SHA256SUMS"] = b"x  README.md\n"
    return members


class TestCheckSecrets:
    def test_clean_archive_passes(self) -> None:
        with release_sandbox("secretscan") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(sandbox / "dist", VERSION)
            archive = write_release_zip(sandbox / "clean.zip", VERSION, _complete_members(sandbox, wheel))
            assert check_secrets(archive, VERSION) == []

    @pytest.mark.parametrize(
        "name",
        [".env", ".env.local", "server.pem", "tokens.db", "client_secrets.json", "credentials.txt"],
    )
    def test_fails_naming_secret_bearing_members(self, name: str) -> None:
        with release_sandbox("secretscan") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(sandbox / "dist", VERSION)
            members = _complete_members(sandbox, wheel)
            members[name] = b"# sensitive\n"
            archive = write_release_zip(sandbox / "name.zip", VERSION, members)
            assert check_secrets(archive, VERSION) == [f"SECRET: {name}"]

    def test_fails_naming_credential_content_in_text_members(self) -> None:
        with release_sandbox("secretscan") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(sandbox / "dist", VERSION)
            members = _complete_members(sandbox, wheel)
            members["manuals/usage.md"] = f'api_key = "{SECRET_LITERAL}"\n'.encode()
            archive = write_release_zip(sandbox / "content.zip", VERSION, members)
            assert check_secrets(archive, VERSION) == ["SECRET: manuals/usage.md"]

    def test_never_reports_the_matched_content(self) -> None:
        with release_sandbox("secretscan") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(sandbox / "dist", VERSION)
            members = _complete_members(sandbox, wheel)
            members["manuals/usage.md"] = f'api_key = "{SECRET_LITERAL}"\n'.encode()
            archive = write_release_zip(sandbox / "leak.zip", VERSION, members)
            problems = check_secrets(archive, VERSION)
            joined = "\n".join(problems)
            assert "usage.md" in joined
            assert SECRET_LITERAL not in joined

    def test_detects_credential_content_hidden_inside_the_wheel(self) -> None:
        with release_sandbox("secretscan") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(
                sandbox / "dist",
                VERSION,
                extra_entries={
                    "schwab_mcp/backdoor.py": f'app_key = "{SECRET_LITERAL}"\n'.encode()
                },
            )
            sources = source_map(sandbox, VERSION, wheel)
            archive = assemble_archive(
                version=VERSION,
                build_dirty=False,
                sources=sources,
                out_zip=sandbox / "whl.zip",
            ).archive_path
            problems = check_secrets(archive, VERSION)
            assert len(problems) == 1
            assert problems[0].startswith("SECRET: ")
            assert SECRET_LITERAL not in problems[0]

    def test_reports_every_offending_member(self) -> None:
        with release_sandbox("secretscan") as sandbox:
            make_release_project(sandbox)
            wheel = make_fake_wheel(sandbox / "dist", VERSION)
            members = _complete_members(sandbox, wheel)
            members[".env"] = b"# env\n"
            members["manuals/usage.md"] = f'client_secret = "{SECRET_LITERAL}"\n'.encode()
            archive = write_release_zip(sandbox / "multi.zip", VERSION, members)
            assert set(check_secrets(archive, VERSION)) == {"SECRET: .env", "SECRET: manuals/usage.md"}
