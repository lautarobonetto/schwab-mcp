"""Shared unit-test helpers (single source of truth — Constitution II)."""

from __future__ import annotations

import json

import requests


def build_response(payload, status: int = 200) -> requests.Response:
    """Build a real ``requests.Response`` carrying a JSON *payload*.

    Mimics the objects the ``schwabdev`` client returns for every API call
    (the SDK does not pre-parse JSON bodies).
    """
    r = requests.Response()
    r.status_code = status
    if payload is not None:
        r._content = json.dumps(payload).encode()
    return r
