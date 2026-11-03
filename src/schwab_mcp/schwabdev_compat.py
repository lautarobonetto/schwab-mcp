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

**In-init flow coverage (regression, bug callback-trailing-slash):**
schwabdev runs its whole interactive authorization INSIDE
``Tokens.__init__`` — with an empty or expired store, init calls
``update_tokens``, which builds the authorize URL
(``...&redirect_uri={self._callback_url}``) and performs the code
exchange with the SAME attribute.  Restoring the exact value only after
``__init__`` returns is therefore too late: the in-init flow would use
the slash-stripped validation spelling and mismatch the portal
registration.  While ``__init__`` runs, the exact configured callback is
published on a :class:`contextvars.ContextVar` and
``Tokens.update_tokens`` restores it onto the instance before
delegating, so the authorize URL, the pasted-URL prompt, and the
exchange all see the literal portal-registered value.
"""

from __future__ import annotations

import contextvars

_SHIM_MARKER = "_schwab_mcp_trailing_slash_shim"

_PENDING_EXACT_CALLBACK: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_schwab_mcp_pending_exact_callback", default=None
)
"""Exact configured callback while ``Tokens.__init__`` is running.

schwabdev's in-init authorization flow reads ``self._callback_url`` to
build the authorize URL and to exchange the code; until init returns,
that attribute holds the slash-stripped validation spelling.  The init
wrapper publishes the exact value here and the ``update_tokens`` wrapper
restores it onto the instance before delegating.
"""


def install_trailing_slash_callback_support() -> None:
    """Make schwabdev accept callback URLs with a single trailing ``/``.

    Idempotent: installing twice is a no-op.  Raises ``RuntimeError`` if
    the expected schwabdev internals are missing (upstream change), so a
    future incompatible release fails loudly instead of silently sending
    a ``redirect_uri`` that mismatches the portal registration.

    The wrap is narrow by design: schwabdev validates ``callback_url``
    and stores it verbatim as ``self._callback_url``, so the shim
    validates with a tolerated spelling and then restores the exact
    configured value — both after ``__init__`` and, crucially, before
    the in-init authorization flow via the ``update_tokens`` wrapper.
    """
    import schwabdev.tokens

    tokens_cls = schwabdev.tokens.Tokens
    if getattr(tokens_cls.__init__, _SHIM_MARKER, False):
        return  # already installed
    original_init = tokens_cls.__init__
    original_update_tokens = getattr(tokens_cls, "update_tokens", None)
    if original_update_tokens is None:
        raise RuntimeError(
            "schwabdev internals changed: Tokens no longer has "
            "'update_tokens'; cannot preserve the trailing-slash callback "
            "URL for the in-init authorization flow. Report this against "
            "schwab-mcp."
        )

    def _restoring_update_tokens(self, *args: object, **kwargs: object):
        """Restore the exact configured callback before any in-init use.

        ``update_tokens`` is the outermost schwabdev method invoked from
        ``__init__`` (both the loaded-store and empty-store paths); the
        authorize-URL build and the code exchange run inside it and read
        ``self._callback_url``.  While init is in progress the exact
        value is published on the ContextVar; afterwards the variable is
        reset and this wrapper is a no-op.
        """
        exact = _PENDING_EXACT_CALLBACK.get()
        if exact is not None:
            self._callback_url = exact
        return original_update_tokens(self, *args, **kwargs)  # type: ignore[misc]

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
        restore_token = _PENDING_EXACT_CALLBACK.set(callback_url)
        try:
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
        finally:
            _PENDING_EXACT_CALLBACK.reset(restore_token)
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
    tokens_cls.update_tokens = _restoring_update_tokens  # type: ignore[method-assign]