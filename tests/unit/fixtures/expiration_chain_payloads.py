"""Live-captured provider expiration-chain payload fixtures (feature 012, T002/T019).

Captured 2026-11-03 with an authorized ``schwabdev`` client against
``GET /marketdata/v1/expirationchain?symbol=AAPL`` (HTTP 200; the T002
fallback flag is cleared — this is live evidence, not a derived shape).
Fixture constants only: no credentials, tokens, or account identifiers
appear below (Credential Safety).

Live facts these fixtures pin (see the implementing commit message):

- the response is ``{"expirationList": [...], "status": null}`` — the
  list key is ``expirationList`` (NOT ``expirations``) and there is no
  ``errorCode`` key;
- each entry carries ``expirationDate`` (``YYYY-MM-DD`` string),
  ``daysToExpiration`` (int — live values are **calendar** days from
  today: 2026-11-04 was reported as 1 on 2026-11-03, matching the local
  calendar-day DTE computation, research R4), ``settlementType``
  (live ``"P"`` for AAPL equity options — pm-settled), plus the raw
  fields ``expirationType`` (``"W"`` weekly / ``"S"`` standard),
  ``optionRoots`` and ``standard``;
- the provider lists every listed expiration out to ~2.2 years
  (24 entries for AAPL on the capture date); the curated DTE ceiling is
  applied client-side (research R1).

If a future capture contradicts any field name below, update ONLY the
provider-key mapping in ``tests/unit/helpers.py``
(``build_expiration_chain_payload``) and ``schwab_mcp.options_chain``
(``_map_expiration_list`` / ``build_expiration_result``) — the curated
schema (``expiration_date``, ``dte``, ``settlement_type``) must not change
(research R2).
"""

from __future__ import annotations


SYMBOL = "AAPL"
"""Liquid optionable symbol used in the live capture."""

CAPTURE_DATE = "2026-11-03"
"""Date of the live capture.

Tests pass ``today=date.fromisoformat(CAPTURE_DATE)`` so the curated ``dte``
values are deterministic against the captured dates.
"""

EXPIRATION_CHAIN_PAYLOAD: dict = {
    "expirationList": [
        {
            "daysToExpiration": 1,
            "expirationDate": "2026-11-04",
            "expirationType": "W",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 3,
            "expirationDate": "2026-11-06",
            "expirationType": "W",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 6,
            "expirationDate": "2026-11-09",
            "expirationType": "W",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 8,
            "expirationDate": "2026-11-11",
            "expirationType": "W",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 10,
            "expirationDate": "2026-11-13",
            "expirationType": "W",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 13,
            "expirationDate": "2026-11-16",
            "expirationType": "W",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 15,
            "expirationDate": "2026-11-18",
            "expirationType": "W",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 17,
            "expirationDate": "2026-11-20",
            "expirationType": "S",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 24,
            "expirationDate": "2026-11-27",
            "expirationType": "W",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 31,
            "expirationDate": "2026-12-04",
            "expirationType": "W",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 38,
            "expirationDate": "2026-12-11",
            "expirationType": "W",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 45,
            "expirationDate": "2026-12-18",
            "expirationType": "S",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 73,
            "expirationDate": "2027-01-15",
            "expirationType": "S",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 108,
            "expirationDate": "2027-02-19",
            "expirationType": "S",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 136,
            "expirationDate": "2027-03-19",
            "expirationType": "S",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 164,
            "expirationDate": "2027-04-16",
            "expirationType": "S",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 226,
            "expirationDate": "2027-06-17",
            "expirationType": "S",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 318,
            "expirationDate": "2027-09-17",
            "expirationType": "S",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 409,
            "expirationDate": "2027-12-17",
            "expirationType": "S",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 444,
            "expirationDate": "2028-01-21",
            "expirationType": "S",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 500,
            "expirationDate": "2028-03-17",
            "expirationType": "S",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 591,
            "expirationDate": "2028-06-16",
            "expirationType": "S",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 773,
            "expirationDate": "2028-12-15",
            "expirationType": "S",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
        {
            "daysToExpiration": 808,
            "expirationDate": "2029-01-19",
            "expirationType": "S",
            "optionRoots": "AAPL",
            "settlementType": "P",
            "standard": True,
        },
    ],
    "status": None,
}

"""The live ``option_expiration_chain("AAPL")`` payload (24 expirations).

The final entries sit far beyond the default 60-day ceiling and exercise
the ``dte_max_effective`` filter against the live shape.
"""