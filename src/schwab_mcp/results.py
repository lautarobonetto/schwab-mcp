"""Shared result taxonomy for multi-account result models.

Single source of the outcome classification, the shared detail values,
the ``AccountFailed`` payload, and the outcome↔field cross-validation
rules common to the result models of feature 003 (open positions) and
feature 006 (transaction history).  Feature modules re-export from here
and add only their feature-specific rules (TD-002).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ResultOutcome(str, Enum):
    """Allowed outcome classifications for a multi-account query result.

    Shared by ``positions.OutcomeType`` and
    ``transactions.TransactionOutcome`` — both are aliases of this class,
    not re-definitions.
    """

    ok = "ok"
    partial_failure = "partial_failure"
    transient_failure = "transient_failure"
    reauth_required = "reauth_required"

    # Uppercase aliases — preserve the positions-style member spellings
    OK = ok
    PARTIAL_FAILURE = partial_failure
    TRANSIENT_FAILURE = transient_failure
    REAUTH_REQUIRED = reauth_required


# Shared detail values (single definition; feature detail enums consume them)
DETAIL_ACCOUNT_FAILED = "account_failed"
DETAIL_PROVIDER_UNREACHABLE = "provider_unreachable"
DETAIL_REAUTH_NEEDED = "reauth_needed"


class AccountFailureDetail(str, Enum):
    """Allowed detail values for accounts_failed entries."""

    provider_error = "provider_error"
    transient = "transient"

    # Uppercase aliases — preserve the positions-style member spellings
    PROVIDER_ERROR = provider_error
    TRANSIENT = transient


class AccountFailed(BaseModel):
    """Describes a single account that failed during a multi-account query.

    Shared by ``positions.AccountFailed`` and
    ``transactions.TransactionAccountFailed`` — both aliases of this
    class, not re-definitions.
    """

    account_hash: str = Field(
        ..., min_length=1, description="Opaque identifier of the failed account"
    )
    detail: AccountFailureDetail = Field(..., description="Reason for the failure")


def validate_shared_outcome_rules(
    outcome: ResultOutcome,
    retryable: bool,
    accounts_failed: Optional[list],
) -> None:
    """Outcome↔field rules shared by every result model.

    Enforces, with the contract error messages (identical in both
    feature data-models: 003 rule D6, 006 rules 4–5):

    - Rule 5: ``retryable=true`` ⇔ ``outcome=transient_failure``
    - Rule 4: ``accounts_failed`` present ⇔ ``outcome=partial_failure``

    Raises ``ValueError`` on violation; feature validators call this
    first and then apply their own feature-specific rules.
    """
    is_transient = outcome == ResultOutcome.transient_failure
    is_partial = outcome == ResultOutcome.partial_failure

    # Rule 5: retryable=true <-> outcome=transient_failure
    if retryable and not is_transient:
        raise ValueError(
            "retryable=True is only allowed when outcome == 'transient_failure'"
        )
    if is_transient and not retryable:
        raise ValueError("transient_failure outcome requires retryable=True")

    # Rule 4: accounts_failed present <-> outcome=partial_failure
    if accounts_failed is not None and not is_partial:
        raise ValueError(
            "accounts_failed is only allowed when outcome == 'partial_failure'"
        )
    if is_partial and accounts_failed is None:
        raise ValueError("partial_failure outcome requires accounts_failed")