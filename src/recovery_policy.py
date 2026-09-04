"""
Recovery Policy.

Given a diagnosed root cause (and the payment's retry history), decides
the single recovery action the agent should take next. Kept as a plain,
readable function -- not a black box -- so every decision can be traced
back to an explicit rule in the pitch/demo and in code review.

Policy summary:
    INSUFFICIENT_FUNDS            -> smart retry after a delay (balance may
                                      top up), then escalate if it keeps failing
    BANK_TIMEOUT_NETWORK          -> smart retry soon (transient issue)
    EXPIRED_CARD                  -> alternate payment method link (retrying
                                      the same expired card can never succeed)
    RISK_DECLINE                  -> escalate to a human reviewer immediately
                                      (never auto-retry a risk block)
    SUBSCRIPTION_MANDATE_FAILURE  -> re-trigger the UPI/e-NACH mandate
    UNKNOWN                       -> escalate to a human reviewer

Regardless of root cause, once a payment has already been retried
MAX_RETRY_ATTEMPTS times, the policy stops retrying and escalates instead
of looping forever -- this is the "one failure handled gracefully" case
called out in the track brief and demoed explicitly in the dashboard.
"""

from __future__ import annotations

from src import config
from src.models import FailedPayment, RecoveryAction, RecoveryDecision, RootCause


def decide(payment: FailedPayment, root_cause: RootCause) -> RecoveryDecision:
    # Safety net: regardless of root cause, a very high risk score always
    # routes to a human -- an automated system should never auto-retry
    # something the risk engine considers highly suspicious.
    if payment.risk_score >= 70:
        return RecoveryDecision(
            payment_id=payment.payment_id,
            action=RecoveryAction.ESCALATE_HUMAN,
            reason=(
                f"Risk score {payment.risk_score:.0f}/100 exceeds the safety threshold (70); "
                f"escalating regardless of diagnosed root cause."
            ),
        )

    # Graceful give-up: too many attempts already made on this payment.
    if payment.attempt_number > config.MAX_RETRY_ATTEMPTS:
        return RecoveryDecision(
            payment_id=payment.payment_id,
            action=RecoveryAction.ESCALATE_HUMAN,
            reason=(
                f"Already retried {payment.attempt_number - 1} time(s), exceeding the "
                f"configured limit of {config.MAX_RETRY_ATTEMPTS}. Escalating instead of "
                f"retrying indefinitely."
            ),
        )

    if root_cause == RootCause.INSUFFICIENT_FUNDS:
        return RecoveryDecision(
            payment_id=payment.payment_id,
            action=RecoveryAction.SMART_RETRY,
            reason=(
                f"Balance may be topped up later; retrying after "
                f"{config.SMART_RETRY_DELAY_HOURS}h instead of failing the customer immediately."
            ),
        )

    if root_cause == RootCause.BANK_TIMEOUT_NETWORK:
        return RecoveryDecision(
            payment_id=payment.payment_id,
            action=RecoveryAction.SMART_RETRY,
            reason="Transient network/bank timeout; an immediate retry is likely to succeed.",
        )

    if root_cause == RootCause.EXPIRED_CARD:
        return RecoveryDecision(
            payment_id=payment.payment_id,
            action=RecoveryAction.ALT_PAYMENT_LINK,
            reason="Retrying an expired card can never succeed; sending a link to pay via another method.",
        )

    if root_cause == RootCause.SUBSCRIPTION_MANDATE_FAILURE:
        return RecoveryDecision(
            payment_id=payment.payment_id,
            action=RecoveryAction.MANDATE_RETRIGGER,
            reason="Recurring mandate execution failed; re-triggering the UPI Autopay / e-NACH mandate.",
        )

    if root_cause == RootCause.RISK_DECLINE:
        return RecoveryDecision(
            payment_id=payment.payment_id,
            action=RecoveryAction.ESCALATE_HUMAN,
            reason="Risk-engine declines are never auto-retried; routing to a human reviewer.",
        )

    # RootCause.UNKNOWN and anything unforeseen.
    return RecoveryDecision(
        payment_id=payment.payment_id,
        action=RecoveryAction.ESCALATE_HUMAN,
        reason="Root cause could not be determined with sufficient confidence; escalating to a human.",
    )
