"""Shared construction of the schwabdev client (single source of truth).

Every entry point (``serve``, ``auth``, ``renew``) needs a client built the
same way.  Centralising construction (Constitution II/III) guarantees that
the configured provider request ``timeout`` is applied everywhere —
schwabdev's 10 s default breaks full-chain fetches at large ``strikeCount``
(bug spx-delta-timeout: ``$SPX`` + ``delta_target`` needs up to 200 strikes
and exceeds 10 s at Schwab's API, surfacing as ``ConnectivityError``).

``schwabdev.Client`` is resolved through the module at call time so that
tests can monkeypatch ``schwabdev.Client`` (same patchability as the
previous per-call-site imports).
"""

from __future__ import annotations

from typing import Any, Callable

import schwabdev

from schwab_mcp.config import Config


def build_schwab_client(
    config: Config,
    tokens_db: str,
    call_on_auth: Callable[[str], str],
) -> Any:
    """Construct the schwabdev client with the configured request timeout.

    Parameters
    ----------
    config
        Validated application configuration; ``config.request_timeout``
        (seconds) is forwarded as the client's provider request timeout.
    tokens_db
        Path of the token store (may differ from ``config.token_db`` during
        backup/restore flows).
    call_on_auth
        The ``call_on_auth`` hook (guard or interactive counting hook).

    Returns
    -------
    The constructed ``schwabdev.Client`` instance.
    """
    return schwabdev.Client(
        config.app_key,
        config.app_secret,
        config.callback_url,
        tokens_db=tokens_db,
        call_on_auth=call_on_auth,
        open_browser_for_auth=False,
        timeout=config.request_timeout,
    )