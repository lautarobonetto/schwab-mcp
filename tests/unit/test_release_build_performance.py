"""Build performance — full build under the SC-002 budget."""

from __future__ import annotations

import time

import pytest

from tests.unit.helpers import REPO_ROOT, release_sandbox

from schwab_mcp_release import cli
from schwab_mcp_release.version import resolve_version


class TestBuildPerformance:
    @pytest.mark.performance
    def test_full_build_completes_under_60_seconds(self, monkeypatch) -> None:
        version = resolve_version(REPO_ROOT)
        with release_sandbox("perf") as out_dir:
            monkeypatch.chdir(REPO_ROOT)
            started = time.monotonic()
            code = cli.main(["build", "--allow-dirty", "--output-dir", str(out_dir)])
            elapsed = time.monotonic() - started
            assert code == 0
            assert elapsed < 60.0, f"full build took {elapsed:.1f}s (SC-002 budget: 60s)"
            assert (out_dir / f"schwab-mcp-{version}.zip").exists()
