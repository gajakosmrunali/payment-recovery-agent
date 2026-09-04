"""
Lightweight SQLite persistence layer.

SQLite is used deliberately instead of Postgres/MySQL: it needs zero setup
(no server, no Docker), ships with Python's standard library, and is more
than enough for a hackathon-scale batch (tens to thousands of payments).
Every table doubles as the audit trail the track's "bar" asks for -- every
row records exactly what the agent decided and did, and when.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from src import config
from src.models import (
    Diagnosis,
    FailedPayment,
    RecoveryDecision,
    RecoveryOutcome,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    payment_id       TEXT PRIMARY KEY,
    customer_id      TEXT NOT NULL,
    amount           REAL NOT NULL,
    currency         TEXT NOT NULL,
    method           TEXT NOT NULL,
    decline_code     TEXT NOT NULL,
    decline_reason   TEXT NOT NULL,
    is_subscription  INTEGER NOT NULL,
    attempt_number   INTEGER NOT NULL,
    created_at       TEXT NOT NULL,
    bank_name        TEXT NOT NULL DEFAULT 'Unknown Bank',
    region           TEXT NOT NULL DEFAULT 'Unknown',
    customer_tier    TEXT NOT NULL DEFAULT 'Regular',
    risk_score       REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS diagnoses (
    payment_id   TEXT PRIMARY KEY,
    root_cause   TEXT NOT NULL,
    confidence   REAL NOT NULL,
    explanation  TEXT NOT NULL,
    FOREIGN KEY (payment_id) REFERENCES payments (payment_id)
);

CREATE TABLE IF NOT EXISTS decisions (
    payment_id  TEXT PRIMARY KEY,
    action      TEXT NOT NULL,
    reason      TEXT NOT NULL,
    FOREIGN KEY (payment_id) REFERENCES payments (payment_id)
);

CREATE TABLE IF NOT EXISTS outcomes (
    payment_id  TEXT PRIMARY KEY,
    action      TEXT NOT NULL,
    status      TEXT NOT NULL,
    amount      REAL NOT NULL,
    detail      TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    FOREIGN KEY (payment_id) REFERENCES payments (payment_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id  TEXT NOT NULL,
    stage       TEXT NOT NULL,
    message     TEXT NOT NULL,
    timestamp   TEXT NOT NULL
);
"""


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(reset: bool = False) -> None:
    """Create all tables. If reset=True, drop and recreate everything so a
    fresh demo run starts from a clean slate."""
    with get_connection() as conn:
        if reset:
            for table in ("audit_log", "outcomes", "decisions", "diagnoses", "payments"):
                conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.executescript(SCHEMA)


def log_event(payment_id: str, stage: str, message: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO audit_log (payment_id, stage, message, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (payment_id, stage, message, datetime.utcnow().isoformat()),
        )


def save_payment(payment: FailedPayment) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO payments
               (payment_id, customer_id, amount, currency, method, decline_code,
                decline_reason, is_subscription, attempt_number, created_at,
                bank_name, region, customer_tier, risk_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payment.payment_id,
                payment.customer_id,
                payment.amount,
                payment.currency,
                payment.method,
                payment.decline_code,
                payment.decline_reason,
                int(payment.is_subscription),
                payment.attempt_number,
                payment.created_at,
                payment.bank_name,
                payment.region,
                payment.customer_tier,
                payment.risk_score,
            ),
        )
    log_event(payment.payment_id, "INGEST", f"Failed payment ingested: {payment.decline_reason}")


def save_diagnosis(diagnosis: Diagnosis) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO diagnoses
               (payment_id, root_cause, confidence, explanation)
               VALUES (?, ?, ?, ?)""",
            (
                diagnosis.payment_id,
                diagnosis.root_cause.value,
                diagnosis.confidence,
                diagnosis.explanation,
            ),
        )
    log_event(
        diagnosis.payment_id,
        "DIAGNOSE",
        f"Root cause: {diagnosis.root_cause.value} (confidence {diagnosis.confidence:.2f})",
    )


def save_decision(decision: RecoveryDecision) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO decisions (payment_id, action, reason)
               VALUES (?, ?, ?)""",
            (decision.payment_id, decision.action.value, decision.reason),
        )
    log_event(decision.payment_id, "DECIDE", f"Action chosen: {decision.action.value} - {decision.reason}")


def save_outcome(outcome: RecoveryOutcome) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO outcomes
               (payment_id, action, status, amount, detail, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                outcome.payment_id,
                outcome.action.value,
                outcome.status.value,
                outcome.amount,
                outcome.detail,
                outcome.timestamp,
            ),
        )
    log_event(outcome.payment_id, "ACT", f"{outcome.status.value}: {outcome.detail}")


def fetch_all(table: str) -> list[sqlite3.Row]:
    with get_connection() as conn:
        cursor = conn.execute(f"SELECT * FROM {table}")
        return cursor.fetchall()


def fetch_dashboard_rows() -> list[sqlite3.Row]:
    """One joined row per payment: ingestion + diagnosis + decision +
    outcome. This is the single query the Streamlit dashboard needs."""
    query = """
    SELECT
        p.payment_id, p.customer_id, p.amount, p.currency, p.method,
        p.decline_code, p.decline_reason, p.is_subscription, p.attempt_number,
        p.created_at, p.bank_name, p.region, p.customer_tier, p.risk_score,
        d.root_cause, d.confidence, d.explanation,
        dec.action AS decided_action, dec.reason AS decision_reason,
        o.status AS outcome_status, o.detail AS outcome_detail, o.timestamp AS outcome_timestamp
    FROM payments p
    LEFT JOIN diagnoses d ON p.payment_id = d.payment_id
    LEFT JOIN decisions dec ON p.payment_id = dec.payment_id
    LEFT JOIN outcomes o ON p.payment_id = o.payment_id
    ORDER BY p.created_at ASC
    """
    with get_connection() as conn:
        cursor = conn.execute(query)
        return cursor.fetchall()


def fetch_audit_log() -> list[sqlite3.Row]:
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM audit_log ORDER BY id ASC")
        return cursor.fetchall()
