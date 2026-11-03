"""No test may ever open a real browser tab (global test-safety fixture).

Regression: 5 auth-flow tests exercised ``schwab_mcp.cli.auth_hook``
without stubbing ``webbrowser.open``, so each run of the suite opened a
real browser tab. The autouse fixture in ``tests/conftest.py`` now
intercepts ``webbrowser.open`` for every test. This module verifies the
fixture is active and behaves as a faithful test double.
"""

from __future__ import annotations

import webbrowser

from tests import conftest


def test_webbrowser_open_is_stubbed_for_every_test() -> None:
    """``webbrowser.open`` must be the conftest test double, never the real one."""
    assert webbrowser.open is conftest.stub_open


def test_stub_open_records_urls_and_succeeds() -> None:
    """The double records the requested URL and returns True (browser opened)."""
    url = "https://api.schwabapi.com/v1/oauth/authorize?client_id=KEY"
    assert conftest.stub_open_calls == []
    assert webbrowser.open(url) is True
    assert conftest.stub_open_calls == [url]


def test_stub_open_supports_webbrowser_signature() -> None:
    """The double accepts the full ``webbrowser.open`` signature."""
    assert (
        webbrowser.open("https://example.invalid", new=2, autoraise=False)
        is True
    )