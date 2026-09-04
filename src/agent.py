"""
Recovery Agent orchestrator.

This is the "agent" in the project's name: for every failed payment it
runs the four-stage loop described in the README --

    INGEST -> DIAGNOSE -> DECIDE -> ACT

-- and persists every stage to SQLite so the outcome is fully auditable
(the dashboard reads straight from this data).
"""

from __future__ import annotations

from dataclasses import dataclass

from src import database
from src.models import FailedPayment, RecoveryOutcome
from src.razorpay_client import RazorpayClient
from src.recovery_policy import decide
from src.root_cause_classifier import classify


@dataclass
class BatchSummary:
    total_payments: int
    total_failed_amount: float
    total_recovered_amount: float
    recovered_count: int
    escalated_count: int
    failed_count: int

    @property
    def recovery_rate(self) -> float:
        if self.total_payments == 0:
            return 0.0
        return self.recovered_count / self.total_payments


class RecoveryAgent:
    def __init__(self, razorpay_client: RazorpayClient | None = None) -> None:
        self.client = razorpay_client or RazorpayClient()

    def process_payment(self, payment: FailedPayment) -> RecoveryOutcome:
        # 1. INGEST
        database.save_payment(payment)

        # 2. DIAGNOSE
        diagnosis = classify(payment)
        database.save_diagnosis(diagnosis)

        # 3. DECIDE
        decision = decide(payment, diagnosis.root_cause)
        database.save_decision(decision)

        # 4. ACT
        outcome = self.client.execute_action(decision.action, payment.payment_id, payment.amount)
        database.save_outcome(outcome)

        return outcome

    def process_batch(self, payments: list[FailedPayment]) -> BatchSummary:
        outcomes = [self.process_payment(p) for p in payments]

        total_failed_amount = sum(p.amount for p in payments)
        recovered = [o for o in outcomes if o.status.value == "RECOVERED"]
        escalated = [o for o in outcomes if o.status.value == "ESCALATED"]
        failed = [o for o in outcomes if o.status.value == "FAILED"]

        return BatchSummary(
            total_payments=len(payments),
            total_failed_amount=total_failed_amount,
            total_recovered_amount=sum(o.amount for o in recovered),
            recovered_count=len(recovered),
            escalated_count=len(escalated),
            failed_count=len(failed),
        )
