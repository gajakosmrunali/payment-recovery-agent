"""
Central configuration for the Payment-Failure Root Cause & Recovery Agent.

All tunable settings live here so the rest of the codebase never hardcodes
paths, thresholds, or mode flags. Values are read from environment variables
(loaded from a .env file via python-dotenv) with sane defaults, so the
project runs out of the box in MOCK mode without any Razorpay credentials.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load variables from a .env file in the project root, if present.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


# --- Mode -------------------------------------------------------------
# When True (default), the RazorpayClient never makes a real network call.
# It simulates realistic API responses so the whole pipeline, dashboard,
# and tests run with zero external setup.
USE_MOCK_RAZORPAY: bool = _get_bool("USE_MOCK_RAZORPAY", True)

# --- Razorpay credentials (only used when USE_MOCK_RAZORPAY=False) ----
RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "")

# --- Storage ------------------------------------------------------------
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_PATH: str = os.getenv("DATABASE_PATH", str(DATA_DIR / "agent.db"))
SYNTHETIC_DATA_PATH: str = os.getenv(
    "SYNTHETIC_DATA_PATH", str(DATA_DIR / "synthetic_payments.json")
)

# --- Synthetic batch size ------------------------------------------------
SYNTHETIC_BATCH_SIZE: int = int(os.getenv("SYNTHETIC_BATCH_SIZE", "60"))
RANDOM_SEED: int = int(os.getenv("RANDOM_SEED", "42"))

# --- Recovery policy tuning ----------------------------------------------
# Maximum number of retry attempts the agent will make for a single payment
# before giving up and escalating to a human (this is the "graceful
# failure" case the pitch / demo should show explicitly).
MAX_RETRY_ATTEMPTS: int = int(os.getenv("MAX_RETRY_ATTEMPTS", "2"))

# Hours to wait before a smart retry for a network/bank-timeout failure.
SMART_RETRY_DELAY_HOURS: int = int(os.getenv("SMART_RETRY_DELAY_HOURS", "6"))
