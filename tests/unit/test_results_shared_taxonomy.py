"""Shared result taxonomy tests (TD-002).

Pins that the positions (003) and transaction-history (006) modules
consume a single shared definition of the outcome enum, the shared
detail values, ``AccountFailed``, and the shared outcome-rules
validator from ``src/schwab_mcp/results.py`` — instead of
re-defining the taxonomy locally.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import schwab_mcp.results as results
from schwab_mcp.positions import (
    AccountFailed as PositionsAccountFailed,
)
from schwab_mcp.positions import (
    AccountFailureDetail as PositionsAccountFailureDetail,
)
from schwab_mcp.positions import DetailType, OutcomeType, PositionsResult
from schwab_mcp.results import (
    AccountFailureDetail,
    AccountFailed,
    ResultOutcome,
    validate_shared_outcome_rules,
)
from schwab_mcp.transactions import (
    TransactionAccountFailed,
    TransactionDetail,
    TransactionOutcome,
    TransactionsResult,
)


class TestOutcomeEnumIdentity:
    """The outcome enum is one shared class, aliased by both modules."""

    def test_modules_share_identity_with_results(self) -> None:
        """positions.OutcomeType and transactions.TransactionOutcome are
        the same class as results.ResultOutcome (true reuse, not
        re-definition)."""
        assert OutcomeType is ResultOutcome
        assert TransactionOutcome is ResultOutcome

    def test_both_member_casings_are_aliases(self) -> None:
        """Both spellings resolve to the same member."""
        assert ResultOutcome.OK is ResultOutcome.ok
        assert ResultOutcome.PARTIAL_FAILURE is ResultOutcome.partial_failure
        assert ResultOutcome.TRANSIENT_FAILURE is ResultOutcome.transient_failure
        assert ResultOutcome.REAUTH_REQUIRED is ResultOutcome.reauth_required

    @pytest.mark.parametrize(
        "member,value",
        [
            ("ok", "ok"),
            ("partial_failure", "partial_failure"),
            ("transient_failure", "transient_failure"),
            ("reauth_required", "reauth_required"),
        ],
    )
    def test_values_preserved(self, member: str, value: str) -> None:
        assert ResultOutcome[member].value == value


class TestSharedDetailValues:
    """The three shared detail values have a single definition."""

    @pytest.mark.parametrize(
        "constant,tx_member,pos_member",
        [
            ("DETAIL_ACCOUNT_FAILED", "account_failed", "ACCOUNT_FAILED"),
            (
                "DETAIL_PROVIDER_UNREACHABLE",
                "provider_unreachable",
                "PROVIDER_UNREACHABLE",
            ),
            ("DETAIL_REAUTH_NEEDED", "reauth_needed", "REAUTH_NEEDED"),
        ],
    )
    def test_single_source(
        self, constant: str, tx_member: str, pos_member: str
    ) -> None:
        """Both feature enums take the shared value from results.py."""
        shared = getattr(results, constant)
        assert TransactionDetail[tx_member].value == shared
        assert DetailType[pos_member].value == shared

    def test_feature_vocabularies_unchanged(self) -> None:
        """Each feature keeps exactly its own vocabulary (no widening)."""
        assert {m.value for m in TransactionDetail} == {
            "history_retrieved",
            "no_movements",
            "no_movements_for_instrument",
            "account_failed",
            "provider_unreachable",
            "reauth_needed",
        }
        assert {m.value for m in DetailType} == {
            "data_received",
            "no_positions",
            "account_failed",
            "provider_unreachable",
            "reauth_needed",
            "store_absent",
            "store_corrupted",
        }


class TestAccountFailedShared:
    """One AccountFailed model / AccountFailureDetail enum, aliased twice."""

    def test_models_share_identity(self) -> None:
        assert PositionsAccountFailed is AccountFailed
        assert TransactionAccountFailed is AccountFailed
        assert PositionsAccountFailureDetail is AccountFailureDetail

    def test_detail_casing_aliases(self) -> None:
        assert AccountFailureDetail.PROVIDER_ERROR is AccountFailureDetail.provider_error
        assert AccountFailureDetail.TRANSIENT is AccountFailureDetail.transient

    def test_detail_values_preserved(self) -> None:
        assert {m.value for m in AccountFailureDetail} == {
            "provider_error",
            "transient",
        }

    def test_free_form_detail_rejected(self) -> None:
        """Tightening: detail accepts only the closed vocabulary
        (transactions previously allowed any str)."""
        with pytest.raises(ValidationError):
            AccountFailed(account_hash="abc", detail="nonsense")

    def test_plain_string_coerces_to_member(self) -> None:
        entry = AccountFailed(account_hash="abc", detail="provider_error")
        assert entry.detail is AccountFailureDetail.provider_error


class TestSharedOutcomeRules:
    """The shared validator enforces rules 4 and 5 with contract messages."""

    def test_retryable_with_non_transient_rejected(self) -> None:
        with pytest.raises(
            ValueError,
            match="retryable=True is only allowed when outcome == 'transient_failure'",
        ):
            validate_shared_outcome_rules(
                ResultOutcome.ok, retryable=True, accounts_failed=None
            )

    def test_transient_requires_retryable(self) -> None:
        with pytest.raises(
            ValueError, match="transient_failure outcome requires retryable=True"
        ):
            validate_shared_outcome_rules(
                ResultOutcome.transient_failure, retryable=False, accounts_failed=None
            )

    def test_accounts_failed_only_with_partial(self) -> None:
        with pytest.raises(
            ValueError,
            match="accounts_failed is only allowed when outcome == 'partial_failure'",
        ):
            validate_shared_outcome_rules(
                ResultOutcome.ok, retryable=False, accounts_failed=[]
            )

    def test_partial_requires_accounts_failed(self) -> None:
        with pytest.raises(
            ValueError, match="partial_failure outcome requires accounts_failed"
        ):
            validate_shared_outcome_rules(
                ResultOutcome.partial_failure, retryable=False, accounts_failed=None
            )

    @pytest.mark.parametrize(
        "outcome,retryable,accounts_failed",
        [
            ("ok", False, None),
            ("transient_failure", True, None),
            ("partial_failure", False, []),
            ("reauth_required", False, None),
        ],
    )
    def test_valid_combinations_pass(
        self, outcome: str, retryable: bool, accounts_failed: list | None
    ) -> None:
        validate_shared_outcome_rules(
            ResultOutcome[outcome], retryable=retryable, accounts_failed=accounts_failed
        )


class TestMessageParity:
    """Both result models raise byte-identical messages for shared rules."""

    def test_rule5_message_identical_across_modules(self) -> None:
        with pytest.raises(ValidationError) as pos_err:
            PositionsResult(
                outcome="ok",
                detail="data_received",
                retryable=True,
                retrieved_at="2026-01-01T00:00:00+00:00",
            )
        with pytest.raises(ValidationError) as tx_err:
            TransactionsResult(
                outcome="ok",
                detail="history_retrieved",
                retryable=True,
                retrieved_at="2026-01-01T00:00:00+00:00",
            )
        pos_msg = pos_err.value.errors()[0]["msg"]
        tx_msg = tx_err.value.errors()[0]["msg"]
        assert pos_msg == tx_msg
        assert (
            "retryable=True is only allowed when outcome == 'transient_failure'"
            in pos_msg
        )

    def test_rule4_message_identical_across_modules(self) -> None:
        accounts = [{"account_hash": "a", "detail": "transient"}]
        with pytest.raises(ValidationError) as pos_err:
            PositionsResult(
                outcome="ok",
                detail="data_received",
                retryable=False,
                accounts_failed=accounts,
                retrieved_at="2026-01-01T00:00:00+00:00",
            )
        with pytest.raises(ValidationError) as tx_err:
            TransactionsResult(
                outcome="ok",
                detail="history_retrieved",
                retryable=False,
                accounts_failed=accounts,
                retrieved_at="2026-01-01T00:00:00+00:00",
            )
        pos_msg = pos_err.value.errors()[0]["msg"]
        tx_msg = tx_err.value.errors()[0]["msg"]
        assert pos_msg == tx_msg
        assert (
            "accounts_failed is only allowed when outcome == 'partial_failure'"
            in pos_msg
        )