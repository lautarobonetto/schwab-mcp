"""Build command contract — stable stdout and exit codes (FR-005, FR-008).

Task T015 (US1): the CLI stdout matches the stable contract lines and the
exit codes are 0 (success — also with ``--allow-dirty``, recording
``build_dirty: true``), 1 (validation failure naming the missing piece),
2 (dirty tree without override, fixed message), 3 (wheel-build
prerequisite failure).  T032 (US3) completes the ``CHECKS`` line with the
``exclusion``/``secrets`` fields and covers the failing-scan exit codes.
"""

from __future__ import annotations

import json
import re
import zipfile

import pytest

from tests.unit.helpers import (
    make_fake_wheel,
    make_release_project,
    release_sandbox,
    run_git,
)

from schwab_mcp_release import cli
from schwab_mcp_release.allowlist import wrap_dir, wheel_name
from schwab_mcp_release.wheel import WheelBuild, WheelBuildError

VERSION = "9.9.9"
ZIP_NAME = f"schwab-mcp-{VERSION}.zip"


@pytest.fixture
def fake_wheel_builder(monkeypatch):
    def build(project_root, out_dir):
        path = make_fake_wheel(out_dir, VERSION)
        return WheelBuild(name=wheel_name(VERSION), path=path)

    monkeypatch.setattr(cli, "build_wheel", build)


@pytest.fixture
def project():
    with release_sandbox("cli") as sandbox:
        make_release_project(sandbox, VERSION)
        yield sandbox


class TestBuildSuccess:
    def test_stdout_matches_the_stable_contract(
        self, project, fake_wheel_builder, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(project)
        assert cli.main(["build"]) == 0
        out = capsys.readouterr().out.splitlines()
        assert out[0] == f"BUILD schwab-mcp {VERSION}"
        assert out[1] == f"WHEEL  {wheel_name(VERSION)}"
        assert re.fullmatch(r"ARCHIVE members=7 bytes=\d+", out[2]), out[2]
        assert out[3] == "CHECKS completeness=PASS exclusion=PASS secrets=PASS"
        assert out[4] == f"OUT    dist/{ZIP_NAME}"
        assert out[5] == f"OUT    dist/{ZIP_NAME}.sha256"
        assert re.fullmatch(r"OK     build complete in \d+\.\d+s", out[6]), out[6]
        assert len(out) == 7

    def test_emits_archive_and_checksum(self, project, fake_wheel_builder, monkeypatch) -> None:
        monkeypatch.chdir(project)
        assert cli.main(["build"]) == 0
        assert (project / "dist" / ZIP_NAME).is_file()
        assert (project / "dist" / f"{ZIP_NAME}.sha256").is_file()

    def test_custom_output_dir(self, project, fake_wheel_builder, monkeypatch) -> None:
        monkeypatch.chdir(project)
        assert cli.main(["build", "--output-dir", "out"]) == 0
        assert (project / "out" / ZIP_NAME).is_file()
        assert (project / "out" / f"{ZIP_NAME}.sha256").is_file()

    def test_staging_is_cleaned_up(self, project, fake_wheel_builder, monkeypatch) -> None:
        monkeypatch.chdir(project)
        assert cli.main(["build"]) == 0
        assert not (project / "tmp" / "release-staging").exists()


class TestAllowDirty:
    def test_dirty_tree_with_override_succeeds_and_is_recorded(
        self, project, fake_wheel_builder, monkeypatch, capsys
    ) -> None:
        run_git(project, "init")
        run_git(project, "add", "-A")
        monkeypatch.chdir(project)
        assert cli.main(["build", "--allow-dirty"]) == 0
        with zipfile.ZipFile(project / "dist" / ZIP_NAME) as zf:
            manifest = json.loads(zf.read(f"{wrap_dir(VERSION)}/manifest.json"))
        assert manifest["build_dirty"] is True

    def test_clean_tree_records_build_dirty_false(
        self, project, fake_wheel_builder, monkeypatch
    ) -> None:
        monkeypatch.chdir(project)
        assert cli.main(["build", "--allow-dirty"]) == 0
        with zipfile.ZipFile(project / "dist" / ZIP_NAME) as zf:
            manifest = json.loads(zf.read(f"{wrap_dir(VERSION)}/manifest.json"))
        assert manifest["build_dirty"] is False


class TestDirtyTreeGuard:
    def test_exit_2_with_the_contract_message(
        self, project, fake_wheel_builder, monkeypatch, capsys
    ) -> None:
        run_git(project, "init")
        run_git(project, "add", "-A")
        monkeypatch.chdir(project)
        assert cli.main(["build"]) == 2
        captured = capsys.readouterr()
        assert "working tree has uncommitted changes; pass --allow-dirty to build anyway" in captured.err
        assert not (project / "dist" / ZIP_NAME).exists()

    def test_clean_git_tree_builds_without_the_flag(
        self, project, fake_wheel_builder, monkeypatch
    ) -> None:
        run_git(project, "init")
        run_git(project, "add", "-A")
        run_git(project, "commit", "-m", "clean")
        monkeypatch.chdir(project)
        assert cli.main(["build"]) == 0


class TestValidationFailure:
    def test_exit_1_naming_the_missing_piece(
        self, project, fake_wheel_builder, monkeypatch, capsys
    ) -> None:
        (project / "docs" / "release" / "installation.md").write_text("")
        monkeypatch.chdir(project)
        assert cli.main(["build"]) == 1
        captured = capsys.readouterr()
        assert "MISSING: manuals/installation.md" in captured.err
        assert not (project / "dist" / ZIP_NAME).exists()
        assert not (project / "dist" / f"{ZIP_NAME}.sha256").exists()

    def test_staging_is_cleaned_up_on_failure(
        self, project, fake_wheel_builder, monkeypatch
    ) -> None:
        (project / "docs" / "release" / "installation.md").write_text("")
        monkeypatch.chdir(project)
        assert cli.main(["build"]) == 1
        assert not (project / "tmp" / "release-staging").exists()


class TestPrerequisiteFailure:
    def test_exit_3_on_wheel_build_failure(
        self, project, monkeypatch, capsys
    ) -> None:
        def boom(project_root, out_dir):
            raise WheelBuildError("wheel build failed: uv exited 1")

        monkeypatch.setattr(cli, "build_wheel", boom)
        monkeypatch.chdir(project)
        assert cli.main(["build"]) == 3
        assert "uv exited 1" in capsys.readouterr().err

    def test_exit_3_on_missing_source_file(
        self, project, fake_wheel_builder, monkeypatch, capsys
    ) -> None:
        (project / "docs" / "release" / "usage.md").unlink()
        monkeypatch.chdir(project)
        assert cli.main(["build"]) == 3
        assert "docs/release/usage.md" in capsys.readouterr().err

    def test_exit_3_when_version_unresolvable(self, project, fake_wheel_builder, monkeypatch, capsys) -> None:
        (project / "pyproject.toml").write_text('[project]\nname = "schwab-mcp"\n')
        monkeypatch.chdir(project)
        assert cli.main(["build"]) == 3
        assert "pyproject.toml" in capsys.readouterr().err


class TestScanFailures:
    """T032 (US3): failing exclusion/secret scans exit 1 naming the member."""

    SECRET_LITERAL = "1234567890abcdef"

    def test_exit_1_on_secret_bearing_source(
        self, project, fake_wheel_builder, monkeypatch, capsys
    ) -> None:
        (project / "docs" / "release" / "usage.md").write_text(
            f'api_key = "{self.SECRET_LITERAL}"\n'
        )
        monkeypatch.chdir(project)
        assert cli.main(["build"]) == 1
        err = capsys.readouterr().err
        assert "SECRET: manuals/usage.md" in err
        assert self.SECRET_LITERAL not in err
        assert not (project / "dist" / ZIP_NAME).exists()
        assert not (project / "dist" / f"{ZIP_NAME}.sha256").exists()

    def test_exit_1_on_dev_material_inside_the_wheel(
        self, project, monkeypatch, capsys
    ) -> None:
        def build(project_root, out_dir):
            path = make_fake_wheel(out_dir, VERSION, extra_entries={"tests/probe.py": b"# probe\n"})
            return WheelBuild(name=wheel_name(VERSION), path=path)

        monkeypatch.setattr(cli, "build_wheel", build)
        monkeypatch.chdir(project)
        assert cli.main(["build"]) == 1
        err = capsys.readouterr().err
        assert "DEV-MATERIAL: " in err
        assert "tests/probe.py" in err
        assert not (project / "dist" / ZIP_NAME).exists()
        assert not (project / "dist" / f"{ZIP_NAME}.sha256").exists()

    def test_staging_is_cleaned_up_on_scan_failure(
        self, project, fake_wheel_builder, monkeypatch
    ) -> None:
        (project / "docs" / "release" / "usage.md").write_text(
            f'api_key = "{self.SECRET_LITERAL}"\n'
        )
        monkeypatch.chdir(project)
        assert cli.main(["build"]) == 1
        assert not (project / "tmp" / "release-staging").exists()
