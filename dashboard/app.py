"""
Streamlit dashboard for the Payment-Failure Root Cause & Recovery Agent.

Run with:
    streamlit run dashboard/app.py

Reads directly from the SQLite database populated by `src/run_pipeline.py`,
so make sure you've run the pipeline at least once before launching this.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import config, database

st.set_page_config(
    page_title="Payment Recovery Agent Dashboard",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Theme constants (kept in one place so charts + custom HTML cards agree)

PRIMARY = "#2952E3"
SUCCESS = "#1FA971"
WARNING = "#E3A72E"
DANGER = "#E34C4C"
MUTED = "#6B7385"
CARD_BG = "#F4F6FB"

ROOT_CAUSE_COLORS = {
    "INSUFFICIENT_FUNDS": "#2952E3",
    "BANK_TIMEOUT_NETWORK": "#5B8DEF",
    "EXPIRED_CARD": "#E3A72E",
    "RISK_DECLINE": "#E34C4C",
    "SUBSCRIPTION_MANDATE_FAILURE": "#8C5AE0",
    "UNKNOWN": "#6B7385",
}

ACTION_COLORS = {
    "SMART_RETRY": "#2952E3",
    "ALT_PAYMENT_LINK": "#1FA971",
    "MANDATE_RETRIGGER": "#8C5AE0",
    "ESCALATE_HUMAN": "#E34C4C",
    "NO_ACTION": "#6B7385",
}

CUSTOM_CSS = f"""
<style>
    .block-container {{ padding-top: 1.6rem; }}
    .kpi-card {{
        background: {CARD_BG};
        border: 1px solid #E4E8F2;
        border-radius: 14px;
        padding: 18px 20px;
        height: 100%;
    }}
    .kpi-label {{
        font-size: 0.82rem;
        font-weight: 600;
        color: {MUTED};
        text-transform: uppercase;
        letter-spacing: 0.03em;
        margin-bottom: 6px;
    }}
    .kpi-value {{
        font-size: 1.75rem;
        font-weight: 700;
        color: #1A2138;
        line-height: 1.1;
    }}
    .kpi-sub {{
        font-size: 0.8rem;
        color: {MUTED};
        margin-top: 4px;
    }}
    .section-tag {{
        display: inline-block;
        background: #E9EEFC;
        color: {PRIMARY};
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        padding: 3px 10px;
        border-radius: 999px;
        margin-bottom: 6px;
    }}
    .escalation-box {{
        background: #FDF1F1;
        border: 1px solid #F5C9C9;
        border-radius: 12px;
        padding: 18px 20px;
    }}
    .mono {{ font-family: 'SFMono-Regular', Consolas, monospace; }}
</style>
"""


@st.cache_data(ttl=5)
def load_data() -> pd.DataFrame:
    rows = database.fetch_dashboard_rows()
    df = pd.DataFrame([dict(r) for r in rows])
    if not df.empty:
        df["created_at_dt"] = pd.to_datetime(df["created_at"])
        df["date"] = df["created_at_dt"].dt.date
    return df


@st.cache_data(ttl=5)
def load_audit_log() -> pd.DataFrame:
    rows = database.fetch_audit_log()
    return pd.DataFrame([dict(r) for r in rows])


def kpi_card(label: str, value: str, sub: str = "", accent: str = PRIMARY) -> str:
    return f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value" style="color:{accent};">{value}</div>
        <div class="kpi-sub">{sub}</div>
    </div>
    """


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    with st.sidebar:
        st.header("Filters")

        root_causes = sorted(df["root_cause"].dropna().unique().tolist())
        selected_causes = st.multiselect("Root cause", root_causes, default=root_causes)

        methods = sorted(df["method"].dropna().unique().tolist())
        selected_methods = st.multiselect("Payment method", methods, default=methods)

        regions = sorted(df["region"].dropna().unique().tolist())
        selected_regions = st.multiselect("Region", regions, default=regions)

        tiers = sorted(df["customer_tier"].dropna().unique().tolist())
        selected_tiers = st.multiselect("Customer tier", tiers, default=tiers)

        filtered = df[
            df["root_cause"].isin(selected_causes)
            & df["method"].isin(selected_methods)
            & df["region"].isin(selected_regions)
            & df["customer_tier"].isin(selected_tiers)
        ]

        st.divider()
        st.header("About this run")
        st.write(f"**Mode:** {'🧪 MOCK' if config.USE_MOCK_RAZORPAY else '🔴 LIVE'}")
        st.write(f"**Max retry attempts:** {config.MAX_RETRY_ATTEMPTS}")
        st.write(f"**Database:** `{Path(config.DATABASE_PATH).name}`")

        if st.button("🔄 Refresh data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        csv_bytes = filtered.drop(columns=["created_at_dt"], errors="ignore").to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download filtered data (CSV)",
            data=csv_bytes,
            file_name="payment_recovery_filtered.csv",
            mime="text/csv",
            use_container_width=True,
        )

    return filtered


def render_header() -> None:
    st.markdown('<span class="section-tag">TRACK 3 · AI REVENUE RECOVERY</span>', unsafe_allow_html=True)
    st.title("💳 Payment-Failure Root Cause & Recovery Agent")
    st.caption(
        "Diagnoses why a payment failed, decides the right recovery action, executes it, "
        "and shows measured money recovered — with a full audit trail."
    )


def render_kpis(df: pd.DataFrame) -> None:
    total_failed = df["amount"].sum()
    recovered_df = df[df["outcome_status"] == "RECOVERED"]
    total_recovered = recovered_df["amount"].sum()
    recovery_rate = (len(recovered_df) / len(df) * 100) if len(df) else 0
    escalated_count = int((df["outcome_status"] == "ESCALATED").sum())
    avg_ticket = df["amount"].mean() if len(df) else 0

    cols = st.columns(5)
    cards = [
        ("Total Failed", f"₹{total_failed:,.0f}", f"{len(df)} payments", PRIMARY),
        ("Total Recovered", f"₹{total_recovered:,.0f}", f"{len(recovered_df)} payments", SUCCESS),
        ("Recovery Rate", f"{recovery_rate:.1f}%", "of all failed payments", SUCCESS if recovery_rate >= 40 else WARNING),
        ("Escalated to Human", f"{escalated_count}", "risk / retry-limit / unknown", DANGER),
        ("Avg. Failed Ticket", f"₹{avg_ticket:,.0f}", "per payment", MUTED),
    ]
    for col, (label, value, sub, accent) in zip(cols, cards):
        with col:
            st.markdown(kpi_card(label, value, sub, accent), unsafe_allow_html=True)


def render_trend_chart(df: pd.DataFrame) -> None:
    st.subheader("📈 Failed vs. Recovered Amount Over Time")
    daily = (
        df.groupby("date")
        .apply(
            lambda g: pd.Series(
                {
                    "Failed Amount": g["amount"].sum(),
                    "Recovered Amount": g.loc[g["outcome_status"] == "RECOVERED", "amount"].sum(),
                }
            )
        )
        .reset_index()
    )
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=daily["date"], y=daily["Failed Amount"], name="Failed",
                              mode="lines+markers", line=dict(color=DANGER, width=2)))
    fig.add_trace(go.Scatter(x=daily["date"], y=daily["Recovered Amount"], name="Recovered",
                              mode="lines+markers", line=dict(color=SUCCESS, width=2), fill="tozeroy"))
    fig.update_layout(
        margin=dict(t=10, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis_title="Amount (₹)",
        height=340,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_outcome_donut(df: pd.DataFrame) -> None:
    st.subheader("Outcome Mix")
    counts = df["outcome_status"].value_counts().reset_index()
    counts.columns = ["Status", "Count"]
    color_map = {"RECOVERED": SUCCESS, "FAILED": DANGER, "ESCALATED": WARNING, "PENDING": MUTED}
    fig = px.pie(
        counts, names="Status", values="Count", hole=0.55,
        color="Status", color_discrete_map=color_map,
    )
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=340)
    st.plotly_chart(fig, use_container_width=True)


def render_recovery_by_root_cause(df: pd.DataFrame) -> None:
    st.subheader("Recovery Rate by Root Cause")
    grouped = (
        df.groupby("root_cause")
        .agg(
            total_payments=("payment_id", "count"),
            recovered=("outcome_status", lambda s: (s == "RECOVERED").sum()),
            failed_amount=("amount", "sum"),
            avg_risk_score=("risk_score", "mean"),
        )
        .reset_index()
    )
    grouped["recovery_rate_pct"] = (grouped["recovered"] / grouped["total_payments"] * 100).round(1)

    fig = px.bar(
        grouped, x="root_cause", y="recovery_rate_pct", color="root_cause",
        color_discrete_map=ROOT_CAUSE_COLORS, text="recovery_rate_pct",
        labels={"root_cause": "Root Cause", "recovery_rate_pct": "Recovery Rate (%)"},
    )
    fig.update_traces(texttemplate="%{text}%", textposition="outside")
    fig.update_layout(showlegend=False, yaxis_range=[0, 100], margin=dict(t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        grouped.rename(columns={
            "root_cause": "Root Cause", "total_payments": "Payments", "recovered": "Recovered",
            "failed_amount": "Total Failed (₹)", "avg_risk_score": "Avg Risk Score",
            "recovery_rate_pct": "Recovery Rate (%)",
        }).round(1),
        use_container_width=True, hide_index=True,
    )


def render_risk_and_segment_breakdown(df: pd.DataFrame) -> None:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Recovery Rate by Customer Tier")
        grouped = (
            df.groupby("customer_tier")
            .agg(total=("payment_id", "count"), recovered=("outcome_status", lambda s: (s == "RECOVERED").sum()))
            .reset_index()
        )
        grouped["rate"] = (grouped["recovered"] / grouped["total"] * 100).round(1)
        fig = px.bar(grouped, x="customer_tier", y="rate", color="customer_tier",
                     text="rate", labels={"customer_tier": "Tier", "rate": "Recovery Rate (%)"})
        fig.update_traces(texttemplate="%{text}%", textposition="outside")
        fig.update_layout(showlegend=False, yaxis_range=[0, 100], margin=dict(t=10, b=10), height=320)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Risk Score Distribution")
        fig = px.histogram(
            df, x="risk_score", nbins=20, color="root_cause",
            color_discrete_map=ROOT_CAUSE_COLORS,
            labels={"risk_score": "Risk Score", "count": "Payments"},
        )
        fig.update_layout(margin=dict(t=10, b=10), height=320,
                           legend=dict(orientation="h", yanchor="bottom", y=1.02))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Failed Amount by Bank & Region")
    col3, col4 = st.columns(2)
    with col3:
        by_bank = df.groupby("bank_name")["amount"].sum().sort_values(ascending=True).reset_index()
        fig = px.bar(by_bank, x="amount", y="bank_name", orientation="h",
                     labels={"amount": "Failed Amount (₹)", "bank_name": ""}, color_discrete_sequence=[PRIMARY])
        fig.update_layout(margin=dict(t=10, b=10), height=320)
        st.plotly_chart(fig, use_container_width=True)
    with col4:
        by_region = df.groupby("region")["amount"].sum().sort_values(ascending=True).reset_index()
        fig = px.bar(by_region, x="amount", y="region", orientation="h",
                     labels={"amount": "Failed Amount (₹)", "region": ""}, color_discrete_sequence=[SUCCESS])
        fig.update_layout(margin=dict(t=10, b=10), height=320)
        st.plotly_chart(fig, use_container_width=True)


def render_action_breakdown(df: pd.DataFrame) -> None:
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("Actions Taken by the Agent")
        action_counts = df["decided_action"].value_counts().reset_index()
        action_counts.columns = ["Action", "Count"]
        fig = px.pie(action_counts, names="Action", values="Count", hole=0.45,
                     color="Action", color_discrete_map=ACTION_COLORS)
        fig.update_layout(margin=dict(t=10, b=10), height=340)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Outcome by Action Taken")
        cross = pd.crosstab(df["decided_action"], df["outcome_status"])
        fig = px.bar(cross, barmode="stack",
                     color_discrete_map={"RECOVERED": SUCCESS, "FAILED": DANGER, "ESCALATED": WARNING, "PENDING": MUTED})
        fig.update_layout(margin=dict(t=10, b=10), height=340, xaxis_title="Action", yaxis_title="Payments")
        st.plotly_chart(fig, use_container_width=True)


def render_graceful_failure_case(df: pd.DataFrame) -> None:
    st.markdown('<span class="section-tag">THE BAR: HANDLE ONE FAILURE GRACEFULLY</span>', unsafe_allow_html=True)
    st.subheader("🛑 Failures Handled Gracefully — Not Retried Endlessly")

    escalated = df[df["decided_action"] == "ESCALATE_HUMAN"].copy()
    if escalated.empty:
        st.info("No escalation case in the current filter/batch. Widen the filters or re-run the pipeline.")
        return

    retry_exceeded = escalated[escalated["decision_reason"].str.contains("exceeding", case=False, na=False)]
    risk_blocked = escalated[escalated["decision_reason"].str.contains("risk score", case=False, na=False)]
    risk_declines = escalated[escalated["root_cause"] == "RISK_DECLINE"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Escalated: retry limit exceeded", len(retry_exceeded))
    c2.metric("Escalated: risk-score safety net", len(risk_blocked))
    c3.metric("Escalated: risk-engine decline", len(risk_declines))

    example = retry_exceeded.iloc[0] if not retry_exceeded.empty else escalated.iloc[0]
    st.markdown(
        f"""
<div class="escalation-box">
<b>Example — payment <span class="mono">{example['payment_id']}</span></b><br><br>
Attempt number: <b>{int(example['attempt_number'])}</b> &nbsp;|&nbsp;
Root cause: <b>{example['root_cause']}</b> &nbsp;|&nbsp;
Risk score: <b>{example['risk_score']:.0f}/100</b><br>
Decision: <b>{example['decided_action']}</b> — {example['decision_reason']}<br>
Outcome: <b>{example['outcome_status']}</b> — {example['outcome_detail']}
</div>
""",
        unsafe_allow_html=True,
    )
    st.caption(
        "Instead of retrying the same payment forever, the policy recognises when a retry "
        "limit, a high risk score, or a risk-engine decline makes further automated retries "
        "unsafe or pointless — and routes it to a human reviewer with full context attached."
    )


def render_payment_explorer(df: pd.DataFrame) -> None:
    st.subheader("🔍 Explore Individual Payments")
    search = st.text_input("Filter by payment_id or customer_id (optional)")
    view_df = df.copy()
    if search:
        mask = view_df["payment_id"].str.contains(search, case=False, na=False) | view_df[
            "customer_id"
        ].str.contains(search, case=False, na=False)
        view_df = view_df[mask]

    display_cols = [
        "payment_id", "customer_id", "amount", "method", "bank_name", "region",
        "customer_tier", "risk_score", "decline_reason", "attempt_number",
        "root_cause", "confidence", "decided_action", "outcome_status", "outcome_detail",
    ]
    st.dataframe(view_df[display_cols], use_container_width=True, hide_index=True, height=420)


def render_audit_trail(audit_df: pd.DataFrame) -> None:
    st.subheader("📜 Full Audit Trail")
    st.caption("Every stage (ingest → diagnose → decide → act) is logged per payment, in order.")
    st.dataframe(audit_df, use_container_width=True, hide_index=True, height=420)


def main() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    render_header()

    df = load_data()
    if df.empty:
        st.warning(
            "No data found in the database yet. Run the pipeline first:\n\n"
            "`python -m src.run_pipeline`\n\nthen refresh this page."
        )
        return

    filtered_df = apply_filters(df)
    if filtered_df.empty:
        st.warning("No payments match the current filters — widen your selection in the sidebar.")
        return

    render_kpis(filtered_df)
    st.divider()

    tab_overview, tab_root_cause, tab_actions, tab_graceful, tab_explorer, tab_audit = st.tabs(
        ["📊 Overview", "🔍 Root Cause Analysis", "⚙️ Recovery Actions",
         "🛑 Graceful Failure", "🧾 Payment Explorer", "📜 Audit Trail"]
    )

    with tab_overview:
        left, right = st.columns([2, 1])
        with left:
            render_trend_chart(filtered_df)
        with right:
            render_outcome_donut(filtered_df)

    with tab_root_cause:
        render_recovery_by_root_cause(filtered_df)
        st.divider()
        render_risk_and_segment_breakdown(filtered_df)

    with tab_actions:
        render_action_breakdown(filtered_df)

    with tab_graceful:
        render_graceful_failure_case(filtered_df)

    with tab_explorer:
        render_payment_explorer(filtered_df)

    with tab_audit:
        audit_df = load_audit_log()
        render_audit_trail(audit_df)


if __name__ == "__main__":
    main()
