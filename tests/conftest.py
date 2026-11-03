"""Global pytest fixtures.

Browser safety: no test may ever open a real browser tab.  The autouse
fixture below replaces ``webbrowser.open`` with a recording test double
for every test, so the auth-flow CLI tests cannot pop browser tabs even
if they forget to stub it themselves.  Tests that need to observe or
alter the outcome (e.g. simulating a failed browser open) simply
``monkeypatch.setattr("webbrowser.open", ...)`` on top of it; per-test
patches win during the test body and are undone before this fixture
restores the original function.
"""

from __future__ import annotations

import webbrowser
from collections.abc import Callable

import pytest

# URLs handed to ``webbrowser.open`` during the current test (reset per test).
stub_open_calls: list[str] = []


def stub_open(url: str, new: int = 0, autoraise: bool = True) -> bool:
    """Test double for ``webbrowser.open``: record the URL, open nothing."""
    stub_open_calls.append(url)
    return True


@pytest.fixture(autouse=True)
def _never_open_a_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``webbrowser.open`` with :func:`stub_open` for every test."""
    stub_open_calls.clear()
    monkeypatch.setattr(webbrowser, "open", stub_open)
    yield