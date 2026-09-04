# Payment-Failure Root Cause & Recovery Agent

**Razorpay Buildathon — Track 3: AI Revenue Recovery**

> Detects *why* a payment failed, decides the right recovery action, executes
> it (against Razorpay's test-mode API or a realistic simulation), and shows
> the measured money recovered across a batch — with every decision logged
> in a full audit trail, and one failure type handled gracefully instead of
> being retried forever.

---

## 1. What this project does

Payments fail for very different reasons — insufficient funds, a bank
network timeout, an expired card, a risk-engine block, a failed UPI
Autopay mandate. Right now, most systems treat all of these the same way
(retry blindly, or just give up). This agent instead runs every failed
payment through a four-stage loop:

```
INGEST  →  DIAGNOSE  →  DECIDE  →  ACT
```

| Stage | What happens |
|---|---|
| **Ingest** | A failed-payment event (shape of a Razorpay `payment.failed` webhook) enters the system. |
| **Diagnose** | A transparent, rule-based classifier maps the decline code to a root cause (e.g. `INSUFFICIENT_FUNDS`, `BANK_TIMEOUT_NETWORK`, `EXPIRED_CARD`, `RISK_DECLINE`, `SUBSCRIPTION_MANDATE_FAILURE`) with a confidence score. |
| **Decide** | A policy chooses the correct recovery action for that root cause — smart retry, alternate payment link, mandate re-trigger, or escalate to a human. Critically: **if a payment has already been retried past a configured limit, the policy stops retrying and escalates instead of looping forever** — this is the "one failure handled gracefully" case. |
| **Act** | The chosen action is executed via a Razorpay API client (mock by default, or real Razorpay TEST-mode calls if you provide test credentials). |

Every stage writes to a SQLite audit log, and a **Streamlit dashboard**
visualizes the results: total amount recovered, recovery rate by root
cause, the actions the agent took, and the graceful-escalation example.

---

## 2. Why it's built this way (for your pitch / code review)

- **Explainable, not a black box.** The root-cause classifier is a plain
  rule table (`src/root_cause_classifier.py`), not an opaque model call —
  for a "money action" system, every decision needs to be auditable. The
  file also shows exactly where an LLM would plug in for genuinely
  ambiguous decline reasons, without requiring an API key to run the demo.
- **Mock mode by default.** `RazorpayClient` (`src/razorpay_client.py`) has
  a `USE_MOCK_RAZORPAY` flag (default `true`). This means the entire
  project — pipeline, tests, dashboard — runs with **zero external
  accounts or API keys**. Flip the flag and add test-mode credentials to
  call Razorpay's real TEST-mode API instead.
- **SQLite, not a hosted database.** Zero setup, ships with Python, and
  every table doubles as the audit trail the track's "bar" asks for.
- **Deterministic where it matters.** The classifier and policy are pure,
  seed-independent logic. Only the *simulated* success/failure of an
  executed action is randomized (and seeded), because in real life you
  can't know in advance whether a retry will succeed — that's the one
  place randomness is honest, not a shortcut.

---

## 3. File structure

```
payment-recovery-agent/
├── README.md                      <- this file
├── requirements.txt                <- Python dependencies
├── pyproject.toml                  <- pytest configuration
├── .env.example                    <- copy to .env; safe defaults, no secrets needed
├── .gitignore
│
├── data/                           <- generated at runtime (gitignored)
│   └── .gitkeep
│
├── src/                            <- all core logic
│   ├── __init__.py
│   ├── config.py                   <- reads .env, exposes all settings
│   ├── models.py                   <- dataclasses & enums (FailedPayment, RootCause, etc.)
│   ├── database.py                 <- SQLite schema + all read/write helpers
│   ├── synthetic_data_generator.py <- generates a realistic failed-payment batch
│   ├── root_cause_classifier.py    <- decline code -> root cause (+ optional LLM fallback hook)
│   ├── recovery_policy.py          <- root cause -> recovery action decision
│   ├── razorpay_client.py          <- executes actions (mock or live Razorpay TEST API)
│   ├── agent.py                    <- orchestrates ingest -> diagnose -> decide -> act
│   └── run_pipeline.py             <- CLI entry point: runs the whole batch end-to-end
│
├── dashboard/
│   └── app.py                      <- Streamlit dashboard (reads straight from SQLite)
│
├── tests/
│   ├── __init__.py
│   └── test_agent.py               <- pytest suite: classifier, policy, agent, DB
│
└── scripts/
    ├── setup.sh                    <- one-time venv + install setup (macOS/Linux)
    └── run_demo.sh                 <- regenerates data, runs pipeline, launches dashboard
```

---

## 4. Setup on macOS (Python 3.14, VS Code)

### 4.1 Prerequisites
- Python 3.14 installed (`python3 --version` to confirm)
- VS Code with the **Python extension** installed

### 4.2 One-time setup

Open the project folder in VS Code, open a terminal (`` Ctrl+` ``), then:

```bash
cd payment-recovery-agent
bash scripts/setup.sh
```

This will:
1. Create a virtual environment at `.venv/`
2. Install everything in `requirements.txt`
3. Copy `.env.example` to `.env` (already correctly configured for mock mode)

**In VS Code:** press `Cmd+Shift+P` → `Python: Select Interpreter` → choose
the one at `./.venv/bin/python` so VS Code runs/debugs with the right
environment.

> **If `pip install` fails on Python 3.14** (a brand-new Python version can
> occasionally lag behind on pre-built wheels for a few packages): install
> [pyenv](https://github.com/pyenv/pyenv) via `brew install pyenv`, then
> `pyenv install 3.12.7 && pyenv local 3.12.7`, and re-run `bash
> scripts/setup.sh`. Every file in this project is plain, version-agnostic
> Python with no 3.14-only syntax, so it runs identically on 3.12/3.13/3.14.

### 4.3 Manual setup (if you prefer not to use the script)

```bash
cd payment-recovery-agent
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

---

## 5. Running the project

### 5.1 Run the recovery pipeline

```bash
source .venv/bin/activate          # if not already active
python -m src.run_pipeline --regenerate
```

You'll see output like:

```
Total failed payments processed : 60
Total amount that failed        : INR 802,508.62
Total amount recovered          : INR 247,842.00
Recovery rate                   : 38.3%
Recovered / Escalated / Failed  : 23 / 15 / 22
Example of a failure handled gracefully (escalated, not endlessly retried):
  payment_id=pay_5dc8db26a8fb4b attempt_number=4 root_cause=SUBSCRIPTION_MANDATE_FAILURE -> action=ESCALATE_HUMAN
  reason: Already retried 3 time(s), exceeding the configured limit of 2. Escalating instead of retrying indefinitely.
```

Flags:
- `--regenerate` — generate a brand-new synthetic batch (otherwise reuses `data/synthetic_payments.json` if it exists)
- `--size N` — batch size when regenerating (default 60, set via `.env`)

### 5.2 Launch the dashboard

```bash
streamlit run dashboard/app.py
```

Opens automatically at `http://localhost:8501`. It's organized into 6 tabs:

- **📊 Overview** — 5 KPI cards (total failed, total recovered, recovery rate, escalated count, avg. ticket size), a failed-vs-recovered amount trend line over time, and an outcome mix donut chart
- **🔍 Root Cause Analysis** — recovery rate by root cause (chart + table), recovery rate by customer tier, a risk-score distribution histogram, and failed-amount breakdowns by bank and by region
- **⚙️ Recovery Actions** — which action the agent chose for each payment (pie chart) and the outcome of each action (stacked bar)
- **🛑 Graceful Failure** — breaks down *why* each escalation happened (retry limit exceeded / risk-score safety net / risk-engine decline) with a worked example, directly answering the track's "handle one failure gracefully" requirement
- **🧾 Payment Explorer** — searchable table of every individual payment with all its attributes (bank, region, tier, risk score) and outcome
- **📜 Audit Trail** — every stage of every payment, in order

The **sidebar** lets you filter everything by root cause, payment method,
region, and customer tier, shows the current run's mode/config, and has a
button to download the currently-filtered data as CSV.

> Run `python -m src.run_pipeline` **before** launching the dashboard —
> it reads from the SQLite database the pipeline populates.

### 5.3 Run the tests

```bash
pytest -v
```

Expect all 13 tests to pass. The suite covers:
- Classifier correctness for every decline code
- Policy correctness for every root cause
- **The graceful-escalation rules specifically** — both retry-limit-exceeded and the high-risk-score safety net
- End-to-end agent processing (single payment and full batch)
- That a generated batch always contains at least one escalation case (so the demo never runs "empty")

### 5.4 Switching to live Razorpay TEST-mode calls (optional)

1. Create a [Razorpay account](https://dashboard.razorpay.com/) and get your **Test Mode** API keys.
2. In `.env`, set:
   ```
   USE_MOCK_RAZORPAY=false
   RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
   RAZORPAY_KEY_SECRET=your_test_secret
   ```
3. Re-run `python -m src.run_pipeline`. The `ALT_PAYMENT_LINK` action will
   now create a real (test-mode) Razorpay Payment Link. Review
   `src/razorpay_client.py`'s `_live_execute` method and Razorpay's current
   API docs before relying on this for a submission — the exact
   parameters for some endpoints may need adjusting to match the latest API version.

---

## 6. What to build out further before submitting (be upfront about this)

Be honest about scope in your pitch — judges respect this more than
pretending it's fully production-ready:

- The classifier is rule-based; a real system would also handle decline
  reasons it's never seen before (the `classify_with_llm_fallback` hook in
  `root_cause_classifier.py` shows exactly where that would go).
- Mock success rates (`MOCK_SUCCESS_RATES` in `razorpay_client.py`) are
  illustrative placeholders, not measured real-world figures — say this
  explicitly in the pitch rather than presenting them as real numbers.
- Bank, region, and customer-tier attributes are generated with light
  correlation logic (see `_risk_score_for` in `synthetic_data_generator.py`)
  so the dashboard breakdowns are directionally meaningful for a demo, but
  they are still synthetic, not sourced from real settlement data.
- Live mode currently covers Payment Links; retry and mandate re-trigger
  live-mode calls are stubbed with clear comments showing the intended
  integration point.

---

## 7. Suggested Git repository setup

```bash
cd payment-recovery-agent
git init
git add .
git commit -m "Initial commit: Payment-Failure Root Cause & Recovery Agent"
```

Create a new empty repo on GitHub (no README/license, since you already
have one), then:

```bash
git remote add origin https://github.com/<your-username>/payment-recovery-agent.git
git branch -M main
git push -u origin main
```

**In your actual GitHub README** (this file, or a shortened version of it), make sure to include:
- A one-line project description + which Razorpay Buildathon track it targets
- A screenshot or two of the dashboard (take these after running the pipeline)
- The setup/run instructions from Section 4–5 above
- A link to or embed of your 5-minute pitch video

---

## 8. What to include in the 5-minute pitch video

A suggested minute-by-minute structure:

| Time | Content |
|---|---|
| **0:00–0:30** | **The problem.** State it in plain numbers: "X% of payments fail for reasons that have nothing to do with the customer wanting to cancel — and most of that revenue is never recovered because nobody diagnoses *why* it failed before deciding what to do." |
| **0:30–1:15** | **Why this is hard / why now.** Different failures need different fixes — retrying an expired card is pointless, and blind retries on a risk-decline can look like fraud abuse. Mention this is exactly Track 3's first example direction ("payment degradation → root cause → recovery action"). |
| **1:15–2:00** | **Architecture walkthrough.** Show the 4-stage diagram (Ingest → Diagnose → Decide → Act). Briefly show the rule table in `root_cause_classifier.py` and the policy in `recovery_policy.py` — emphasize *explainability*: every action can be traced to a specific rule. |
| **2:00–3:30** | **Live demo.** Run `python -m src.run_pipeline --regenerate` on screen, then switch to the Streamlit dashboard. Walk through: total failed amount → total recovered → recovery rate by root cause chart → the actions-taken pie chart. |
| **3:30–4:15** | **The graceful-failure case.** Explicitly click into the escalation example in the dashboard. Say out loud: "this payment was retried three times and kept failing — instead of retrying forever, the policy recognizes the limit and hands it to a human with full context." This directly answers the track's stated bar. |
| **4:15–4:45** | **Honesty about limitations / what's next.** State clearly what's mocked vs. real (Section 6 above), and what you'd build next (LLM fallback for unseen decline reasons, live Razorpay integration for all action types, calibrating success rates against real settlement data). |
| **4:45–5:00** | **Close.** Restate the one number that matters: "Recovered ₹X of ₹Y in failed payments across this batch — with every decision auditable." |

**Screen-recording tips:**
- Record your terminal + browser dashboard directly (QuickTime Player →
  File → New Screen Recording works fine on macOS).
- Re-run the pipeline once right before recording so the numbers on
  screen are fresh and you're not explaining a stale screenshot.
- Keep code shown on screen to the two files that matter most for
  explainability (`root_cause_classifier.py`, `recovery_policy.py`) —
  don't scroll through every file, it eats your 5 minutes fast.

---

## 9. Quick troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` for `src` when running scripts | Always run commands from the project root (`payment-recovery-agent/`), using `python -m src.run_pipeline`, not `python src/run_pipeline.py`. |
| Dashboard says "No data found" | Run `python -m src.run_pipeline` first — the dashboard only reads existing data, it doesn't generate any. |
| `pip install` fails on a fresh Python 3.14 for one package | See the pyenv fallback note in Section 4.2 — install Python 3.12 or 3.13 via pyenv and re-run setup; no code changes needed. |
| Port 8501 already in use | `streamlit run dashboard/app.py --server.port 8502` |
| Want a bigger/smaller demo batch | Edit `SYNTHETIC_BATCH_SIZE` in `.env`, or pass `--size N` to `run_pipeline`. |
