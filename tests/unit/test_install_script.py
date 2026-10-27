"""Recipient install script — prerequisites, install, upgrade (FR-012, FR-015).

Task T023 (US2): run ``install.sh`` in a sandbox under ``tmp/`` with an
overridden ``HOME``:

- the missing-prerequisite path prints the actionable message matching
  the ``manuals/installation.md`` wording;
- the success path creates the venv, installs the bundled wheel, and
  ``schwab-mcp --help`` works;
- re-running (upgrade) replaces the install in place, and the
  overridden-``HOME`` sandbox proves nothing was written under
  ``~/.schwab-mcp/``.

The success path installs a dependency-free synthetic wheel so the test
is fully offline; the real wheel's dependencies come from the network at
recipient install time (documented prerequisite).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.unit.helpers import REPO_ROOT, make_fake_wheel, release_sandbox

INSTALL_SH = REPO_ROOT / "src" / "schwab_mcp_release" / "install.sh"
INSTALLATION_MANUAL = REPO_ROOT / "docs" / "release" / "installation.md"

MISSING_PYTHON_MSG = (
    "ERROR: python3 not found. Install Python 3.11 or newer and try again. "
    'See manuals/installation.md, section "Prerequisites".'
)
TOO_OLD_MSG_TEMPLATE = (
    "ERROR: Python 3.11 or newer is required (found {version}). Install a newer "
    'Python and try again. See manuals/installation.md, section "Prerequisites".'
)


def _recipient_sandbox(sandbox: Path) -> Path:
    """Lay out the package folder + overridden HOME as a recipient sees it."""
    (sandbox / "dist").mkdir(parents=True, exist_ok=True)
    (INSTALL_SH).read_text()
    (sandbox / "install.sh").write_text(INSTALL_SH.read_text())
    home = sandbox / "home"
    home.mkdir(exist_ok=True)
    return home


def _run_install(sandbox: Path, env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "HOME": str(sandbox / "home"), **env_overrides}
    return subprocess.run(
        ["/bin/sh", "install.sh"],
        cwd=sandbox,
        capture_output=True,
        text=True,
        env=env,
    )


def _make_fake_python3(bin_dir: Path, version: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "python3"
    script.write_text(f'#!/bin/sh\necho "Python {version}"\n')
    script.chmod(0o755)


class TestMissingPrerequisite:
    def test_python3_not_found_message_matches_the_manual(self) -> None:
        with release_sandbox("install") as sandbox:
            _recipient_sandbox(sandbox)
            make_fake_wheel(sandbox / "dist", "9.9.9")
            result = _run_install(sandbox, {"PATH": "/nonexistent", "PYTHON": "python3"})
            assert result.returncode != 0
            assert MISSING_PYTHON_MSG in result.stderr
            assert MISSING_PYTHON_MSG in INSTALLATION_MANUAL.read_text()

    def test_too_old_python_message_matches_the_manual(self) -> None:
        with release_sandbox("install") as sandbox:
            _recipient_sandbox(sandbox)
            make_fake_wheel(sandbox / "dist", "9.9.9")
            bin_dir = sandbox / "bin"
            _make_fake_python3(bin_dir, "3.9.18")
            result = _run_install(sandbox, {"PATH": f"{bin_dir}:/usr/bin:/bin", "PYTHON": "python3"})
            assert result.returncode != 0
            expected = TOO_OLD_MSG_TEMPLATE.format(version="3.9.18")
            assert expected in result.stderr
            documented = TOO_OLD_MSG_TEMPLATE.format(version="<version>")
            assert documented in INSTALLATION_MANUAL.read_text()

    def test_missing_wheel_message_matches_the_manual(self) -> None:
        with release_sandbox("install") as sandbox:
            _recipient_sandbox(sandbox)  # no wheel in dist/
            result = _run_install(sandbox, {"PYTHON": sys.executable})
            assert result.returncode != 0
            assert "ERROR: bundled wheel not found (dist/*.whl)." in result.stderr
            assert "ERROR: bundled wheel not found (dist/*.whl)." in INSTALLATION_MANUAL.read_text()


class TestSuccessfulInstall:
    def test_creates_venv_installs_wheel_and_cli_works(self) -> None:
        with release_sandbox("install") as sandbox:
            _recipient_sandbox(sandbox)
            make_fake_wheel(sandbox / "dist", "9.9.9")
            result = _run_install(sandbox, {"PYTHON": sys.executable})
            assert result.returncode == 0, result.stderr
            assert "OK: installation complete." in result.stdout
            assert (sandbox / ".venv" / "bin" / "schwab-mcp").is_file()
            check = subprocess.run(
                [str(sandbox / ".venv" / "bin" / "schwab-mcp"), "--help"],
                capture_output=True,
                text=True,
            )
            assert check.returncode == 0

    def test_never_writes_to_the_credential_store_path(self) -> None:
        with release_sandbox("install") as sandbox:
            home = _recipient_sandbox(sandbox)
            make_fake_wheel(sandbox / "dist", "9.9.9")
            assert _run_install(sandbox, {"PYTHON": sys.executable}).returncode == 0
            assert not (home / ".schwab-mcp").exists()


class TestUpgradeInPlace:
    def test_rerun_replaces_the_install(self) -> None:
        with release_sandbox("install") as sandbox:
            _recipient_sandbox(sandbox)
            make_fake_wheel(sandbox / "dist", "9.9.9")
            env = {"PYTHON": sys.executable}
            assert _run_install(sandbox, env).returncode == 0
            stale = sandbox / ".venv" / "STALE-MARKER"
            stale.write_text("old install")
            assert _run_install(sandbox, env).returncode == 0
            assert not stale.exists()

    def test_rerun_preserves_the_credential_store(self) -> None:
        with release_sandbox("install") as sandbox:
            home = _recipient_sandbox(sandbox)
            make_fake_wheel(sandbox / "dist", "9.9.9")
            env = {"PYTHON": sys.executable}
            assert _run_install(sandbox, env).returncode == 0
            store = home / ".schwab-mcp" / "tokens.db"
            store.parent.mkdir(parents=True, exist_ok=True)
            store.write_text("recipient credentials")
            assert _run_install(sandbox, env).returncode == 0
            assert store.read_text() == "recipient credentials"
