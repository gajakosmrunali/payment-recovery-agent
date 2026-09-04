"""
Root Cause Classifier.

Maps a raw decline code/reason string (as it would arrive from a Razorpay
webhook) onto one of the RootCause categories the recovery policy
understands, with a confidence score and a human-readable explanation.

Design note: this is intentionally a transparent, rule-based classifier
rather than an opaque model call. For a finance/payments use case,
*explainability* is exactly what the track's "bar" asks for ("every money
action explainable") -- a rule table you can read top to bottom is easier
to audit than a black-box prediction. The `classify_with_llm_fallback`
function below shows where an LLM call would plug in for genuinely
ambiguous/unseen decline reasons, without being required for the demo to
run (keeping the project dependency-light and key-free by default).
"""

from __future__ import annotations

from src.models import Diagnosis, FailedPayment, RootCause

# decline_code -> (RootCause, confidence, explanation template)
CODE_RULES: dict[str, tuple[RootCause, float, str]] = {
    "BAD001": (
        RootCause.INSUFFICIENT_FUNDS,
        0.95,
        "Decline code BAD001 indicates the customer's account/card had insufficient balance.",
    ),
    "NET002": (
        RootCause.BANK_TIMEOUT_NETWORK,
        0.90,
        "Decline code NET002 indicates a transient bank/gateway network timeout, not a customer-side issue.",
    ),
    "CARD003": (
        RootCause.EXPIRED_CARD,
        0.97,
        "Decline code CARD003 indicates the card on file has expired.",
    ),
    "RISK004": (
        RootCause.RISK_DECLINE,
        0.85,
        "Decline code RISK004 indicates the transaction was blocked by a risk/fraud rule.",
    ),
    "MANDATE005": (
        RootCause.SUBSCRIPTION_MANDATE_FAILURE,
        0.92,
        "Decline code MANDATE005 indicates a recurring UPI Autopay / e-NACH mandate execution failure.",
    ),
}

DEFAULT_RULE = (
    RootCause.UNKNOWN,
    0.40,
    "No matching rule for this decline code; falling back to UNKNOWN with low confidence.",
)


def classify(payment: FailedPayment) -> Diagnosis:
    """Deterministic, rule-based classification. This is what the pipeline
    uses by default (USE_MOCK_RAZORPAY has no bearing on this -- the
    classifier never calls Razorpay; it only reasons about the decline
    code already present on the failed-payment event)."""
    root_cause, confidence, explanation = CODE_RULES.get(payment.decline_code, DEFAULT_RULE)

    # Subscription context sharpens an otherwise-generic diagnosis.
    if payment.is_subscription and root_cause == RootCause.UNKNOWN:
        root_cause = RootCause.SUBSCRIPTION_MANDATE_FAILURE
        confidence = 0.55
        explanation = "Unrecognised decline code on a subscription payment; treated as a mandate failure."

    return Diagnosis(
        payment_id=payment.payment_id,
        root_cause=root_cause,
        confidence=confidence,
        explanation=explanation,
    )


def classify_with_llm_fallback(payment: FailedPayment, llm_call=None) -> Diagnosis:
    """Optional extension point.

    If you want to plug in a real LLM for genuinely ambiguous/unseen
    decline reasons, pass a `llm_call(prompt: str) -> str` function that
    hits your provider of choice, and route low-confidence rule-based
    diagnoses through it. Left out of the default pipeline so the project
    has zero required API keys and is fully reproducible offline.
    """
    diagnosis = classify(payment)
    if diagnosis.confidence >= 0.6 or llm_call is None:
        return diagnosis

    prompt = (
        f"A payment failed with decline_code={payment.decline_code!r}, "
        f"reason={payment.decline_reason!r}, method={payment.method!r}, "
        f"is_subscription={payment.is_subscription}. "
        f"Classify the root cause as one of: {[c.value for c in RootCause]}. "
        f"Reply with only the category name."
    )
    try:
        raw_response = llm_call(prompt).strip().upper()
        matched = next((c for c in RootCause if c.value == raw_response), None)
        if matched:
            return Diagnosis(
                payment_id=payment.payment_id,
                root_cause=matched,
                confidence=0.65,
                explanation=f"LLM fallback classification for an ambiguous decline reason: {payment.decline_reason!r}.",
            )
    except Exception:
        # Never let an optional enhancement break the pipeline -- fall
        # back to the rule-based diagnosis if the LLM call fails.
        pass

    return diagnosis
