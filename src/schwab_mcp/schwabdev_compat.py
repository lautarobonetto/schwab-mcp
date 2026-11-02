"""Runtime compatibility shim for schwabdev's callback-URL validation.

schwabdev (4.0.0, latest on PyPI) rejects any callback URL ending in
``/``: ``Tokens.__init__`` raises
``ValueError: [Schwabdev] callback_url cannot be a path (ends with "/").``
The Schwab developer portal, however, may REQUIRE the trailing slash in
the registered callback, and Schwab compares the ``redirect_uri``
character for character against that registration (trailing slash
included) — so the configured value must reach both the authorize URL
and the token exchange EXACTLY as registered (bug
callback-trailing-slash, 2026-11-02).

This module relaxes ONLY that validation, at runtime: a callback ending
in a single ``/`` passes validation (a double ``//`` is still rejected)
and the exact configured value is stored on the ``Tokens`` instance
afterwards.  The shim lives in this package — NOT in site-packages —
so it survives ``uv sync``; patching the vendored library file instead
is fragile and is NOT the supported mechanism.
"""

from __future__ import annotations

_SHIM_MARKER = "_schwab_mcp_trailing_slash_shim"


def install_trailing_slash_callback_support() -> None:
    """Make schwabdev accept callback URLs with a single trailing ``/``.

    Idempotent: installing twice is a no-op.  Raises ``RuntimeError`` if
    the expected schwabdev internals are missing (upstream change), so a
    future incompatible release fails loudly instead of silently sending
    a ``redirect_uri`` that mismatches the portal registration.

    The wrap is narrow by design: schwabdev validates ``callback_url``
    and stores it verbatim as ``self._callback_url``, so the shim
    validates with a tolerated spelling and then restores the exact
    configured value.
    """
    import schwabdev.tokens

    tokens_cls = schwabdev.tokens.Tokens
    if getattr(tokens_cls.__init__, _SHIM_MARKER, False):
        return  # already installed
    original_init = tokens_cls.__init__

    def _shimmed_init(
        self,
        app_key=None,
        app_secret=None,
        callback_url=None,
        logger=None,
        tokens_db="~/.schwabdev/tokens.db",
        encryption=None,
        call_for_auth=None,
        open_browser_for_auth=True,
    ) -> None:
        # Validate with a spelling schwabdev tolerates...
        workable = callback_url
        if (
            isinstance(callback_url, str)
            and callback_url.endswith("/")
            and not callback_url.endswith("//")
        ):
            workable = callback_url[:-1]
        original_init(
            self,
            app_key,
            app_secret,
            workable,
            logger,
            tokens_db,
            encryption,
            call_for_auth,
            open_browser_for_auth,
        )
        # ...then restore the exact configured value for authorize/exchange.
        if workable != callback_url:
            if "_callback_url" not in vars(self):
                raise RuntimeError(
                    "schwabdev internals changed: Tokens no longer stores "
                    "'_callback_url'; cannot preserve the trailing-slash "
                    "callback URL. Report this against schwab-mcp."
                )
            self._callback_url = callback_url

    _shimmed_init._schwab_mcp_trailing_slash_shim = True  # type: ignore[attr-defined]
    tokens_cls.__init__ = _shimmed_init
