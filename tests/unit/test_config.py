"""Unit tests for config loading (T005).

Tests verify the config module's contract per contracts/configuration.md:
- Missing/empty env vars → MissingConfigError (FR-008, fail fast)
- Optional vars with correct defaults (FR-012)
- Invalid token DB paths → InvalidConfigError before filesystem access
- Secrets registered with redaction filter (FR-006)
- No duplicated format validation (DRY — schwabdev owns it)

These tests MUST FAIL when run against the current codebase because
src/schwab_mcp/config.py does not exist yet (TDD red phase).
"""

import os

import pytest

from schwab_mcp.config import load_config
from schwab_mcp.errors import MissingConfigError, InvalidConfigError
from schwab_mcp.log import register_secret


class TestRequiredCredentials:
    """FR-008: Missing or empty credentials → MissingConfigError (exit 2)."""

    def test_missing_app_key_raises_error(self, monkeypatch):
        """Missing SCHWAB_APP_KEY → MissingConfigError."""
        monkeypatch.delenv("SCHWAB_APP_KEY", raising=False)
        monkeypatch.setenv("SCHWAB_APP_SECRET", "some_secret")
        with pytest.raises(MissingConfigError):
            load_config()

    def test_missing_app_secret_raises_error(self, monkeypatch):
        """Missing SCHWAB_APP_SECRET → MissingConfigError."""
        monkeypatch.setenv("SCHWAB_APP_KEY", "some_key")
        monkeypatch.delenv("SCHWAB_APP_SECRET", raising=False)
        with pytest.raises(MissingConfigError):
            load_config()

    def test_both_missing_raises_error(self, monkeypatch):
        """Both env vars missing → MissingConfigError."""
        monkeypatch.delenv("SCHWAB_APP_KEY", raising=False)
        monkeypatch.delenv("SCHWAB_APP_SECRET", raising=False)
        with pytest.raises(MissingConfigError):
            load_config()

    def test_empty_app_key_raises_error(self, monkeypatch):
        """Empty string app key → MissingConfigError."""
        monkeypatch.setenv("SCHWAB_APP_KEY", "")
        monkeypatch.setenv("SCHWAB_APP_SECRET", "some_secret")
        with pytest.raises(MissingConfigError):
            load_config()

    def test_whitespace_app_key_raises_error(self, monkeypatch):
        """Whitespace-only app key → MissingConfigError (strip check)."""
        monkeypatch.setenv("SCHWAB_APP_KEY", "   ")
        monkeypatch.setenv("SCHWAB_APP_SECRET", "some_secret")
        with pytest.raises(MissingConfigError):
            load_config()

    def test_empty_app_secret_raises_error(self, monkeypatch):
        """Empty string app secret → MissingConfigError."""
        monkeypatch.setenv("SCHWAB_APP_KEY", "some_key")
        monkeypatch.setenv("SCHWAB_APP_SECRET", "")
        with pytest.raises(MissingConfigError):
            load_config()

    def test_whitespace_app_secret_raises_error(self, monkeypatch):
        """Whitespace-only app secret → MissingConfigError (strip check)."""
        monkeypatch.setenv("SCHWAB_APP_KEY", "some_key")
        monkeypatch.setenv("SCHWAB_APP_SECRET", "   ")
        with pytest.raises(MissingConfigError):
            load_config()


class TestOptionalVars:
    """FR-012: Optional env vars with sensible defaults."""

    def test_callback_url_default_when_unset(self, monkeypatch):
        """SCHWAB_CALLBACK_URL defaults to https://127.0.0.1."""
        monkeypatch.setenv("SCHWAB_APP_KEY", "some_key")
        monkeypatch.setenv("SCHWAB_APP_SECRET", "some_secret")
        monkeypatch.delenv("SCHWAB_CALLBACK_URL", raising=False)
        config = load_config()
        assert config["callback_url"] == "https://127.0.0.1"

    def test_callback_url_custom_value(self, monkeypatch):
        """Custom SCHWAB_CALLBACK_URL is honoured."""
        monkeypatch.setenv("SCHWAB_APP_KEY", "some_key")
        monkeypatch.setenv("SCHWAB_APP_SECRET", "some_secret")
        monkeypatch.setenv("SCHWAB_CALLBACK_URL", "https://custom.example.com")
        config = load_config()
        assert config["callback_url"] == "https://custom.example.com"

    def test_token_db_default_when_unset(self, monkeypatch):
        """SCHWAB_TOKEN_DB defaults to ~/.schwab-mcp/tokens.db, EXPANDED to
        an absolute path (FR-012: the default must be usable by the
        filesystem APIs — a literal ``~`` crashes os.open/os.stat)."""
        monkeypatch.setenv("SCHWAB_APP_KEY", "some_key")
        monkeypatch.setenv("SCHWAB_APP_SECRET", "some_secret")
        monkeypatch.delenv("SCHWAB_TOKEN_DB", raising=False)
        config = load_config()
        assert config["token_db"] == os.path.expanduser("~/.schwab-mcp/tokens.db")
        assert not config["token_db"].startswith("~"), (
            "token_db must be an expanded absolute path, not a literal '~' path"
        )

    def test_token_db_custom_value(self, monkeypatch):
        """Custom SCHWAB_TOKEN_DB is honoured."""
        monkeypatch.setenv("SCHWAB_APP_KEY", "some_key")
        monkeypatch.setenv("SCHWAB_APP_SECRET", "some_secret")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", "/custom/path/tokens.db")
        config = load_config()
        assert config["token_db"] == "/custom/path/tokens.db"

    def test_token_db_custom_value_with_tilde_is_expanded(self, monkeypatch):
        """A custom SCHWAB_TOKEN_DB containing ``~`` is expanded to the
        owner's home directory (FR-012)."""
        monkeypatch.setenv("SCHWAB_APP_KEY", "some_key")
        monkeypatch.setenv("SCHWAB_APP_SECRET", "some_secret")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", "~/my-tokens/tokens.db")
        config = load_config()
        assert config["token_db"] == os.path.expanduser("~/my-tokens/tokens.db")
        assert not config["token_db"].startswith("~")


class TestInvalidTokenDbPath:
    """Invalid SCHWAB_TOKEN_DB values → InvalidConfigError before filesystem access."""

    def test_token_db_trailing_slash_raises_error(self, monkeypatch):
        """Token DB path ending with '/' → InvalidConfigError."""
        monkeypatch.setenv("SCHWAB_APP_KEY", "some_key")
        monkeypatch.setenv("SCHWAB_APP_SECRET", "some_secret")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", "/some/dir/")
        with pytest.raises(InvalidConfigError):
            load_config()

    def test_token_db_empty_raises_error(self, monkeypatch):
        """Empty SCHWAB_TOKEN_DB → InvalidConfigError."""
        monkeypatch.setenv("SCHWAB_APP_KEY", "some_key")
        monkeypatch.setenv("SCHWAB_APP_SECRET", "some_secret")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", "")
        with pytest.raises(InvalidConfigError):
            load_config()

    def test_token_db_whitespace_raises_error(self, monkeypatch):
        """Whitespace-only SCHWAB_TOKEN_DB → InvalidConfigError."""
        monkeypatch.setenv("SCHWAB_APP_KEY", "some_key")
        monkeypatch.setenv("SCHWAB_APP_SECRET", "some_secret")
        monkeypatch.setenv("SCHWAB_TOKEN_DB", "   ")
        with pytest.raises(InvalidConfigError):
            load_config()


class TestRedactionIntegration:
    """FR-006: Loaded credentials registered with the redaction filter."""

    def test_app_key_and_secret_registered_with_redaction(self, monkeypatch):
        """load_config() calls register_secret() for both app_key and app_secret."""
        app_key = "test_app_key"
        app_secret = "test_app_secret"
        monkeypatch.setenv("SCHWAB_APP_KEY", app_key)
        monkeypatch.setenv("SCHWAB_APP_SECRET", app_secret)
        monkeypatch.delenv("SCHWAB_CALLBACK_URL", raising=False)
        monkeypatch.delenv("SCHWAB_TOKEN_DB", raising=False)

        registered_secrets = []

        def spy_register_secret(value: str) -> None:
            registered_secrets.append(value)

        monkeypatch.setattr("schwab_mcp.log.register_secret", spy_register_secret)

        load_config()

        assert app_key in registered_secrets, (
            "app_key must be registered with the redaction filter (FR-006)"
        )
        assert app_secret in registered_secrets, (
            "app_secret must be registered with the redaction filter (FR-006)"
        )


class TestDryFormatValidation:
    """DRY: No format/length validation duplicated — schwabdev owns it."""

    def test_short_values_not_rejected_by_config(self, monkeypatch):
        """load_config() must NOT reject values that are too short or format-invalid;
        those checks belong to schwabdev (DRY)."""
        monkeypatch.setenv("SCHWAB_APP_KEY", "key")  # intentionally short
        monkeypatch.setenv("SCHWAB_APP_SECRET", "secret")  # intentionally short
        monkeypatch.delenv("SCHWAB_CALLBACK_URL", raising=False)
        monkeypatch.delenv("SCHWAB_TOKEN_DB", raising=False)

        # load_config() should only check presence/non-emptiness, NOT format.
        try:
            config = load_config()
        except (MissingConfigError, InvalidConfigError):
            pytest.fail(
                "load_config() rejected non-empty values based on format; "
                "format validation is schwabdev's responsibility (DRY)"
            )

        assert config["app_key"] == "key"
        assert config["app_secret"] == "secret"