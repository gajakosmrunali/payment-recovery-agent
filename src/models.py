"""
Data models shared across the ingestion, diagnosis, policy, and reporting
layers. Using dataclasses (instead of a heavier ORM) keeps the project
dependency-light and easy to read for anyone reviewing the code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class RootCause(str, Enum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    BANK_TIMEOUT_NETWORK = "BANK_TIMEOUT_NETWORK"
    EXPIRED_CARD = "EXPIRED_CARD"
    RISK_DECLINE = "RISK_DECLINE"
    SUBSCRIPTION_MANDATE_FAILURE = "SUBSCRIPTION_MANDATE_FAILURE"
    UNKNOWN = "UNKNOWN"


class RecoveryAction(str, Enum):
    SMART_RETRY = "SMART_RETRY"
    ALT_PAYMENT_LINK = "ALT_PAYMENT_LINK"
    MANDATE_RETRIGGER = "MANDATE_RETRIGGER"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"
    NO_ACTION = "NO_ACTION"


class RecoveryStatus(str, Enum):
    RECOVERED = "RECOVERED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    PENDING = "PENDING"


@dataclass
class FailedPayment:
    """A single failed-payment event, as it would arrive via a Razorpay
    payment.failed webhook (fields simplified/renamed for clarity), plus
    extra context attributes (bank, region, customer tier, risk score)
    that a real system would enrich the raw webhook with -- these power
    the deeper breakdowns in the dashboard."""

    payment_id: str
    customer_id: str
    amount: float
    currency: str
    method: str  # card, upi, netbanking, wallet
    decline_code: str
    decline_reason: str
    is_subscription: bool
    attempt_number: int
    created_at: str  # ISO timestamp string

    # Enrichment attributes (added for richer analytics / dashboard cuts)
    bank_name: str = "Unknown Bank"
    region: str = "Unknown"
    customer_tier: str = "Regular"  # New, Regular, VIP
    risk_score: float = 0.0         # 0-100, higher = riskier (from a risk engine)


@dataclass
class Diagnosis:
    payment_id: str
    root_cause: RootCause
    confidence: float
    explanation: str


@dataclass
class RecoveryDecision:
    payment_id: str
    action: RecoveryAction
    reason: str


@dataclass
class RecoveryOutcome:
    payment_id: str
    action: RecoveryAction
    status: RecoveryStatus
    amount: float
    detail: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
