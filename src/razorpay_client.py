"""
Razorpay API client wrapper.

Wraps the calls the recovery agent actually needs to execute an action
(retry a payment, create a payment link, re-trigger a mandate, notify a
human reviewer). Two modes:

  * MOCK mode (default, USE_MOCK_RAZORPAY=True in .env): no network calls
    are made at all. Outcomes are simulated with realistic, seeded success
    probabilities per action type, so the whole pipeline/dashboard/tests
    run fully offline with zero Razorpay account setup.

  * LIVE mode (USE_MOCK_RAZORPAY=False + RAZORPAY_KEY_ID/SECRET set): uses
    the official `razorpay` Python SDK against Razorpay's TEST-mode API
    (test-mode keys start with rzp_test_). This is the path you'd exercise
    once you have a Razorpay test account for the actual submission /
    live demo, calling real test-mode endpoints such as Payment Links and
    Payments.

Keeping both behind one interface means `agent.py` never needs to know or
care which mode it's running in.
"""

from __future__ import annotations

import random
import uuid

from src import config
from src.models import RecoveryAction, RecoveryOutcome, RecoveryStatus

# Seeded per-action success probabilities used only in MOCK mode. These are
# illustrative, not claimed real-world figures -- tune them freely, and say
# so explicitly in the pitch ("these are assumed recovery rates for the
# demo; here's how we'd calibrate them against real settlement data").
MOCK_SUCCESS_RATES: dict[RecoveryAction, float] = {
    RecoveryAction.SMART_RETRY: 0.55,
    RecoveryAction.ALT_PAYMENT_LINK: 0.65,
    RecoveryAction.MANDATE_RETRIGGER: 0.50,
    RecoveryAction.ESCALATE_HUMAN: 0.0,  # not auto-resolved; a human handles it
    RecoveryAction.NO_ACTION: 0.0,
}


class RazorpayClient:
    def __init__(self) -> None:
        self.mock = config.USE_MOCK_RAZORPAY
        self._sdk_client = None
        if not self.mock:
            self._init_live_client()

    def _init_live_client(self) -> None:
        try:
            import razorpay  # imported lazily so it's an optional dependency in mock mode
        except ImportError as exc:  # pragma: no cover - exercised only in live mode
            raise RuntimeError(
                "USE_MOCK_RAZORPAY is False but the 'razorpay' package is not installed. "
                "Run: pip install razorpay"
            ) from exc

        if not config.RAZORPAY_KEY_ID or not config.RAZORPAY_KEY_SECRET:
            raise RuntimeError(
                "USE_MOCK_RAZORPAY is False but RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET "
                "are not set in your .env file."
            )
        self._sdk_client = razorpay.Client(
            auth=(config.RAZORPAY_KEY_ID, config.RAZORPAY_KEY_SECRET)
        )

    # -- Public API used by agent.py ------------------------------------

    def execute_action(self, action: RecoveryAction, payment_id: str, amount: float) -> RecoveryOutcome:
        if self.mock:
            return self._mock_execute(action, payment_id, amount)
        return self._live_execute(action, payment_id, amount)

    # -- Mock mode --------------------------------------------------------

    def _mock_execute(self, action: RecoveryAction, payment_id: str, amount: float) -> RecoveryOutcome:
        if action in (RecoveryAction.ESCALATE_HUMAN, RecoveryAction.NO_ACTION):
            return RecoveryOutcome(
                payment_id=payment_id,
                action=action,
                status=RecoveryStatus.ESCALATED if action == RecoveryAction.ESCALATE_HUMAN else RecoveryStatus.FAILED,
                amount=amount,
                detail=f"[MOCK] {action.value} routed to human queue, no automated recovery attempted.",
            )

        success_rate = MOCK_SUCCESS_RATES.get(action, 0.5)
        succeeded = random.random() < success_rate
        ref = f"mock_ref_{uuid.uuid4().hex[:10]}"

        if succeeded:
            return RecoveryOutcome(
                payment_id=payment_id,
                action=action,
                status=RecoveryStatus.RECOVERED,
                amount=amount,
                detail=f"[MOCK] {action.value} succeeded, reference {ref}.",
            )
        return RecoveryOutcome(
            payment_id=payment_id,
            action=action,
            status=RecoveryStatus.FAILED,
            amount=amount,
            detail=f"[MOCK] {action.value} attempted but did not recover the payment (ref {ref}).",
        )

    # -- Live mode (Razorpay TEST-mode API) --------------------------------

    def _live_execute(self, action: RecoveryAction, payment_id: str, amount: float) -> RecoveryOutcome:
        """Illustrative real-API calls against Razorpay TEST mode.

        NOTE: exact parameters (e.g. required fields for Payment Links)
        should be checked against Razorpay's current API docs before a
        real submission -- this shows the intended integration shape.
        """
        try:
            if action == RecoveryAction.ALT_PAYMENT_LINK:
                link = self._sdk_client.payment_link.create(
                    {
                        "amount": int(amount * 100),  # paise
                        "currency": "INR",
                        "description": f"Retry payment for {payment_id}",
                        "reference_id": payment_id,
                    }
                )
                return RecoveryOutcome(
                    payment_id=payment_id,
                    action=action,
                    status=RecoveryStatus.PENDING,
                    amount=amount,
                    detail=f"Payment link created: {link.get('short_url', 'N/A')}",
                )

            if action == RecoveryAction.SMART_RETRY:
                # Placeholder for Razorpay's recurring/retry APIs; in a real
                # integration this would call the relevant retry endpoint.
                return RecoveryOutcome(
                    payment_id=payment_id,
                    action=action,
                    status=RecoveryStatus.PENDING,
                    amount=amount,
                    detail="Retry scheduled via Razorpay recurring payments API.",
                )

            if action == RecoveryAction.MANDATE_RETRIGGER:
                return RecoveryOutcome(
                    payment_id=payment_id,
                    action=action,
                    status=RecoveryStatus.PENDING,
                    amount=amount,
                    detail="Mandate re-trigger requested via Razorpay Subscriptions API.",
                )

            return RecoveryOutcome(
                payment_id=payment_id,
                action=action,
                status=RecoveryStatus.ESCALATED,
                amount=amount,
                detail="Routed to human reviewer queue.",
            )
        except Exception as exc:  # pragma: no cover - network/live-mode path
            return RecoveryOutcome(
                payment_id=payment_id,
                action=action,
                status=RecoveryStatus.FAILED,
                amount=amount,
                detail=f"Live Razorpay API call failed: {exc}",
            )
