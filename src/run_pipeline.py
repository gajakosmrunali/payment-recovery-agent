"""
Main pipeline entry point.

Run this to execute the full demo end to end:
    python -m src.run_pipeline

It will:
  1. Reset and initialise the SQLite database.
  2. Generate (or reuse) a synthetic batch of failed payments.
  3. Run every payment through the Recovery Agent (diagnose -> decide -> act).
  4. Print a human-readable summary to the terminal, including the
     "graceful failure" escalation case for the pitch/demo.

After running this, launch the dashboard with:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import argparse

from src import config, database
from src.agent import RecoveryAgent
from src.synthetic_data_generator import generate_batch, load_batch, save_batch


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Payment-Failure Recovery Agent pipeline.")
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Generate a fresh synthetic batch instead of reusing an existing one.",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=config.SYNTHETIC_BATCH_SIZE,
        help="Number of synthetic failed payments to generate (only used with --regenerate).",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("Payment-Failure Root Cause & Recovery Agent -- pipeline run")
    print("=" * 70)
    print(f"Mode: {'MOCK (no real Razorpay calls)' if config.USE_MOCK_RAZORPAY else 'LIVE'}")

    database.init_db(reset=True)

    batch = None
    if not args.regenerate:
        try:
            batch = load_batch()
            print(f"Loaded existing synthetic batch ({len(batch)} payments) from {config.SYNTHETIC_DATA_PATH}")
        except Exception:
            batch = None  # fall through to generation below

    if batch is None:
        batch = generate_batch(size=args.size)
        save_batch(batch)
        print(f"Generated a new synthetic batch of {len(batch)} payments -> {config.SYNTHETIC_DATA_PATH}")

    agent = RecoveryAgent()
    summary = agent.process_batch(batch)

    print("-" * 70)
    print(f"Total failed payments processed : {summary.total_payments}")
    print(f"Total amount that failed        : INR {summary.total_failed_amount:,.2f}")
    print(f"Total amount recovered          : INR {summary.total_recovered_amount:,.2f}")
    print(f"Recovery rate                   : {summary.recovery_rate * 100:.1f}%")
    print(f"Recovered / Escalated / Failed  : {summary.recovered_count} / {summary.escalated_count} / {summary.failed_count}")
    print("-" * 70)

    escalated_rows = [
        row for row in database.fetch_dashboard_rows() if row["outcome_status"] == "ESCALATED"
    ]
    if escalated_rows:
        example = escalated_rows[0]
        print("Example of a failure handled gracefully (escalated, not endlessly retried):")
        print(
            f"  payment_id={example['payment_id']} attempt_number={example['attempt_number']} "
            f"root_cause={example['root_cause']} -> action={example['decided_action']}"
        )
        print(f"  reason: {example['decision_reason']}")
    print("=" * 70)
    print("Run the dashboard with: streamlit run dashboard/app.py")


if __name__ == "__main__":
    main()
