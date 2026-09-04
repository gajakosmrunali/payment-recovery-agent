"""
Test suite for the Payment-Failure Root Cause & Recovery Agent.

Run with:
    pytest -v

Tests never touch a real Razorpay account -- RazorpayClient is used in
MOCK mode throughout (the project default), so this suite is fully
offline and deterministic where it matters (classifier + policy), and
uses a fixed random seed for the one probabilistic component (mock
outcome success/failure).
"""

from __future__ import annotations

import random

import pytest

from src import config, database
from src.agent import RecoveryAgent
from src.models import FailedPayment, RootCause
from src.razorpay_client import RazorpayClient
from src.recovery_policy import decide
from src.root_cause_classifier import classify
from src.synthetic_data_generator import generate_batch


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Point the database layer at a throwaway SQLite file for every test,
    so tests never touch data/agent.db (your real demo data) or each other."""
    test_db_path = tmp_path / "test_agent.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db_path))
    database.init_db(reset=True)
    yield
    # tmp_path is cleaned up automatically by pytest


def make_payment(**overrides) -> FailedPayment:
    defaults = dict(
        payment_id="pay_test0000001",
        customer_id="cust_0001",
        amount=1000.0,
        currency="INR",
        method="card",
        decline_code="BAD001",
        decline_reason="Insufficient funds in account",
        is_subscription=False,
        attempt_number=1,
        created_at="2026-01-01T00:00:00",
        bank_name="HDFC Bank",
        region="Maharashtra",
        customer_tier="Regular",
        risk_score=20.0,
    )
    defaults.update(overrides)
    return FailedPayment(**defaults)


# ---------------------------------------------------------------------
# Root cause classifier
# ---------------------------------------------------------------------

def test_classifier_maps_known_decline_codes():
    payment = make_payment(decline_code="BAD001")
    diagnosis = classify(payment)
    assert diagnosis.root_cause == RootCause.INSUFFICIENT_FUNDS
    assert diagnosis.confidence > 0.8


def test_classifier_handles_network_timeout():
    payment = make_payment(decline_code="NET002", decline_reason="Bank server timeout")
    diagnosis = classify(payment)
    assert diagnosis.root_cause == RootCause.BANK_TIMEOUT_NETWORK


def test_classifier_falls_back_to_unknown_for_unrecognised_code():
    payment = make_payment(decline_code="ZZZ999", decline_reason="Something new", is_subscription=False)
    diagnosis = classify(payment)
    assert diagnosis.root_cause == RootCause.UNKNOWN
    assert diagnosis.confidence < 0.6


def test_classifier_treats_unknown_subscription_as_mandate_failure():
    payment = make_payment(decline_code="ZZZ999", is_subscription=True)
    diagnosis = classify(payment)
    assert diagnosis.root_cause == RootCause.SUBSCRIPTION_MANDATE_FAILURE


# ---------------------------------------------------------------------
# Recovery policy
# ---------------------------------------------------------------------

def test_policy_retries_insufficient_funds():
    payment = make_payment(attempt_number=1)
    decision = decide(payment, RootCause.INSUFFICIENT_FUNDS)
    assert decision.action.value == "SMART_RETRY"


def test_policy_never_retries_risk_decline():
    payment = make_payment(attempt_number=1)
    decision = decide(payment, RootCause.RISK_DECLINE)
    assert decision.action.value == "ESCALATE_HUMAN"


def test_policy_sends_alt_link_for_expired_card():
    payment = make_payment(attempt_number=1)
    decision = decide(payment, RootCause.EXPIRED_CARD)
    assert decision.action.value == "ALT_PAYMENT_LINK"


def test_policy_escalates_after_max_retry_attempts_exceeded():
    """This is the 'graceful failure' behaviour: once attempt_number goes
    past the configured limit, the policy must stop retrying regardless
    of root cause, and escalate instead."""
    payment = make_payment(attempt_number=config.MAX_RETRY_ATTEMPTS + 1)
    decision = decide(payment, RootCause.INSUFFICIENT_FUNDS)
    assert decision.action.value == "ESCALATE_HUMAN"
    assert "exceeding" in decision.reason.lower()


def test_policy_escalates_high_risk_score_regardless_of_root_cause():
    """A second, independent safety net: even a root cause that would
    normally be auto-retried (e.g. insufficient funds) must be escalated
    if the payment's risk score is very high."""
    payment = make_payment(attempt_number=1, risk_score=85.0)
    decision = decide(payment, RootCause.INSUFFICIENT_FUNDS)
    assert decision.action.value == "ESCALATE_HUMAN"
    assert "risk score" in decision.reason.lower()


def test_policy_allows_normal_retry_when_risk_score_is_low():
    payment = make_payment(attempt_number=1, risk_score=15.0)
    decision = decide(payment, RootCause.INSUFFICIENT_FUNDS)
    assert decision.action.value == "SMART_RETRY"


# ---------------------------------------------------------------------
# End-to-end agent + database round trip
# ---------------------------------------------------------------------

def test_agent_processes_single_payment_and_persists_all_stages():
    agent = RecoveryAgent(razorpay_client=RazorpayClient())
    payment = make_payment()
    outcome = agent.process_payment(payment)

    assert outcome.payment_id == payment.payment_id
    assert outcome.status.value in {"RECOVERED", "FAILED", "ESCALATED"}

    rows = database.fetch_dashboard_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["payment_id"] == payment.payment_id
    assert row["root_cause"] is not None
    assert row["decided_action"] is not None
    assert row["outcome_status"] is not None

    audit_rows = database.fetch_audit_log()
    stages = {r["stage"] for r in audit_rows}
    assert {"INGEST", "DIAGNOSE", "DECIDE", "ACT"}.issubset(stages)


def test_agent_processes_batch_and_summary_counts_are_consistent():
    random.seed(1)
    agent = RecoveryAgent(razorpay_client=RazorpayClient())
    batch = generate_batch(size=25, seed=1)
    summary = agent.process_batch(batch)

    assert summary.total_payments == 25
    assert summary.recovered_count + summary.escalated_count + summary.failed_count == 25
    assert summary.total_failed_amount == pytest.approx(sum(p.amount for p in batch))
    assert 0.0 <= summary.recovery_rate <= 1.0


def test_batch_includes_at_least_one_graceful_escalation_case():
    """Guards against the demo accidentally shipping a batch with zero
    escalations, which would leave the pitch's 'handled gracefully'
    talking point with nothing to show."""
    batch = generate_batch(size=80, seed=config.RANDOM_SEED)
    agent = RecoveryAgent(razorpay_client=RazorpayClient())
    agent.process_batch(batch)

    rows = database.fetch_dashboard_rows()
    escalated = [r for r in rows if r["decided_action"] == "ESCALATE_HUMAN"]
    assert len(escalated) > 0
