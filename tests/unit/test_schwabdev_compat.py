"""Unit tests for the schwabdev trailing-slash callback compat shim.

schwabdev 4.0.0 rejects callback URLs ending in ``/``, but the Schwab
developer portal may REQUIRE the trailing slash in the registered
callback and compares ``redirect_uri`` character for character.  The
shim relaxes only that validation at runtime, from this package (so it
survives ``uv sync``).
"""

from __future__ import annotations

import pytest

import schwabdev.tokens

from schwab_mcp.schwabdev_compat import install_trailing_slash_callback_support

# Even lengths, combined >= 32: satisfies schwabdev's credential check.
_KEY = "0123456789abcdef"
_SECRET = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def original_tokens_init(monkeypatch):
    """Record the pristine ``Tokens.__init__`` so the shim is undone
    automatically at teardown (monkeypatch restores this exact object)."""
    monkeypatch.setattr(
        schwabdev.tokens.Tokens, "__init__", schwabdev.tokens.Tokens.__init__
    )
    return schwabdev.tokens.Tokens.__init__


def _build_tokens(tmp_path, callback_url):
    return schwabdev.tokens.Tokens(
        _KEY,
        _SECRET,
        callback_url,
        tokens_db=str(tmp_path / "tokens.db"),
    )


def test_single_trailing_slash_accepted_and_preserved(tmp_path, original_tokens_init):
    """A callback ending in exactly one '/' passes validation and is
    stored EXACTLY as configured (authorize + exchange need the literal
    portal-registered value)."""
    install_trailing_slash_callback_support()
    tokens = _build_tokens(tmp_path, "https://127.0.0.1/")
    assert tokens._callback_url == "https://127.0.0.1/"


def test_plain_callback_untouched(tmp_path, original_tokens_init):
    """Callbacks without a trailing slash behave exactly as upstream."""
    install_trailing_slash_callback_support()
    tokens = _build_tokens(tmp_path, "https://127.0.0.1")
    assert tokens._callback_url == "https://127.0.0.1"


def test_double_trailing_slash_still_rejected(tmp_path, original_tokens_init):
    """The shim relaxes ONLY a single trailing '/': '//' stays an error."""
    install_trailing_slash_callback_support()
    with pytest.raises(ValueError, match="callback_url"):
        _build_tokens(tmp_path, "https://127.0.0.1//")


def test_install_is_idempotent(tmp_path, original_tokens_init):
    """Installing twice must not double-wrap ``Tokens.__init__``."""
    install_trailing_slash_callback_support()
    first = schwabdev.tokens.Tokens.__init__
    install_trailing_slash_callback_support()
    assert schwabdev.tokens.Tokens.__init__ is first
    # And the relaxed behavior still works after the second install.
    tokens = _build_tokens(tmp_path, "https://127.0.0.1/")
    assert tokens._callback_url == "https://127.0.0.1/"


def test_shim_fails_loudly_if_internals_change(
    tmp_path, original_tokens_init, monkeypatch
):
    """If a future schwabdev stops storing ``_callback_url``, the shim
    must raise a clear RuntimeError instead of silently sending a
    redirect_uri that mismatches the portal registration."""
    install_trailing_slash_callback_support()

    # Simulate an upstream change: the original init stores nothing
    # (and carries no shim marker, so install() wraps it again).
    def _no_storage_init(self, *args, **kwargs):
        self._logger = None

    monkeypatch.setattr(schwabdev.tokens.Tokens, "__init__", _no_storage_init)
    install_trailing_slash_callback_support()

    with pytest.raises(RuntimeError, match="schwabdev internals changed"):
        _build_tokens(tmp_path, "https://127.0.0.1/")
