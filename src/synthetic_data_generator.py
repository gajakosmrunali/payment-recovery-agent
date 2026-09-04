"""
Generates a realistic synthetic batch of failed-payment events, in the
shape a Razorpay `payment.failed` webhook would deliver (fields simplified
for readability). Used because the project runs in MOCK mode by default --
no real merchant data or live Razorpay account is required to demo it.

Run directly to (re)generate the batch file:
    python -m src.synthetic_data_generator
"""

from __future__ import annotations

import json
import random
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta

from src import config
from src.models import FailedPayment

# Each entry: (decline_code, decline_reason, method, weight)
DECLINE_PROFILES = [
    ("BAD001", "Insufficient funds in account", "card", 5),
    ("BAD001", "Insufficient funds in account", "upi", 4),
    ("NET002", "Bank server timeout", "netbanking", 4),
    ("NET002", "Payment gateway network drop", "upi", 3),
    ("CARD003", "Card expired", "card", 3),
    ("RISK004", "Transaction declined by risk engine", "card", 3),
    ("RISK004", "Transaction declined by risk engine", "wallet", 1),
    ("MANDATE005", "UPI autopay mandate execution failed", "upi", 4),
    ("MANDATE005", "e-NACH mandate execution failed", "netbanking", 2),
    ("UNK006", "Unclassified gateway error", "card", 1),
]

CUSTOMER_POOL_SIZE = 40

BANKS = [
    "HDFC Bank", "ICICI Bank", "State Bank of India", "Axis Bank",
    "Kotak Mahindra Bank", "Punjab National Bank", "Yes Bank", "IDFC First Bank",
]

REGIONS = [
    "Maharashtra", "Karnataka", "Delhi NCR", "Tamil Nadu",
    "Uttar Pradesh", "West Bengal", "Gujarat", "Telangana",
]

CUSTOMER_TIERS_WEIGHTED = [("New", 3), ("Regular", 5), ("VIP", 2)]


def _weighted_pick(options_with_weights):
    total = sum(w for _, w in options_with_weights)
    r = random.uniform(0, total)
    upto = 0
    for value, weight in options_with_weights:
        upto += weight
        if r <= upto:
            return value
    return options_with_weights[-1][0]


def _risk_score_for(decline_code: str, customer_tier: str) -> float:
    """Risk scores are generated to be *consistent* with the scenario, not
    fully random: RISK_DECLINE cases should plausibly score high, VIP
    customers plausibly score lower on average. This keeps the dashboard's
    risk-score breakdown meaningful rather than pure noise."""
    base = 20.0
    if decline_code == "RISK004":
        base = 78.0
    elif decline_code == "MANDATE005":
        base = 30.0
    elif decline_code == "BAD001":
        base = 25.0

    tier_adjustment = {"VIP": -12.0, "Regular": 0.0, "New": 10.0}.get(customer_tier, 0.0)
    noise = random.uniform(-8, 8)
    score = base + tier_adjustment + noise
    return round(max(0.0, min(100.0, score)), 1)


def _weighted_choice(profiles):
    total = sum(p[3] for p in profiles)
    r = random.uniform(0, total)
    upto = 0
    for profile in profiles:
        upto += profile[3]
        if r <= upto:
            return profile
    return profiles[-1]


def generate_batch(size: int = None, seed: int = None) -> list[FailedPayment]:
    size = size or config.SYNTHETIC_BATCH_SIZE
    random.seed(seed if seed is not None else config.RANDOM_SEED)

    customers = [f"cust_{i:04d}" for i in range(CUSTOMER_POOL_SIZE)]
    batch: list[FailedPayment] = []
    now = datetime.utcnow()

    for i in range(size):
        decline_code, decline_reason, method, _ = _weighted_choice(DECLINE_PROFILES)
        is_subscription = decline_code == "MANDATE005" or random.random() < 0.15
        created_at = now - timedelta(hours=random.randint(0, 96))

        # ~10% of payments simulate a customer who has already been
        # retried before (attempt_number > 1). This is what lets the
        # recovery policy's "graceful give-up after MAX_RETRY_ATTEMPTS"
        # branch actually trigger in the demo batch, instead of only
        # existing as dead code.
        attempt_number = 1
        if random.random() < 0.10:
            attempt_number = random.choice([2, 3, 4])

        customer_tier = _weighted_pick(CUSTOMER_TIERS_WEIGHTED)
        bank_name = random.choice(BANKS)
        region = random.choice(REGIONS)
        risk_score = _risk_score_for(decline_code, customer_tier)

        payment = FailedPayment(
            payment_id=f"pay_{uuid.uuid4().hex[:14]}",
            customer_id=random.choice(customers),
            amount=round(random.uniform(199, 24999), 2),
            currency="INR",
            method=method,
            decline_code=decline_code,
            decline_reason=decline_reason,
            is_subscription=is_subscription,
            attempt_number=attempt_number,
            created_at=created_at.isoformat(),
            bank_name=bank_name,
            region=region,
            customer_tier=customer_tier,
            risk_score=risk_score,
        )
        batch.append(payment)

    return batch


def save_batch(batch: list[FailedPayment], path: str = None) -> str:
    path = path or config.SYNTHETIC_DATA_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(p) for p in batch], f, indent=2)
    return path


def load_batch(path: str = None) -> list[FailedPayment]:
    path = path or config.SYNTHETIC_DATA_PATH
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [FailedPayment(**item) for item in raw]


if __name__ == "__main__":
    generated = generate_batch()
    out_path = save_batch(generated)
    total_amount = sum(p.amount for p in generated)
    print(f"Generated {len(generated)} synthetic failed payments -> {out_path}")
    print(f"Total failed amount: INR {total_amount:,.2f}")
