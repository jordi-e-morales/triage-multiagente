"""New Application page — mortgage application form + live pipeline execution."""
import streamlit as st
import uuid
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agents.pipeline import run_pipeline, AGENTS
from pages._pipeline_view import render_pipeline_view


def render():
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)
    st.markdown("# New Mortgage Application")
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)

    # If a run is in progress / just completed, show the pipeline view
    if st.session_state.get("active_run"):
        render_pipeline_view(st.session_state.active_run)
        if st.button("← Start New Application"):
            st.session_state.active_run = None
            st.rerun()
        return

    with st.form("mortgage_form"):
        st.markdown("### Borrower Information")
        col1, col2 = st.columns(2)
        with col1:
            first_name = st.text_input("First Name", value="John")
            annual_income = st.number_input("Annual Income ($)", min_value=10000, max_value=2000000,
                                             value=95000, step=1000)
            employment_status = st.selectbox("Employment Status",
                ["Full-time", "Part-time", "Self-employed", "Contract", "Retired"])
        with col2:
            last_name = st.text_input("Last Name", value="Smith")
            credit_score = st.slider("Credit Score", 300, 850, 720)
            employment_years = st.number_input("Years at Current Employer", 0.0, 40.0, 5.0, 0.5)

        monthly_debts = st.number_input("Total Monthly Debt Payments ($)", 0, 20000, 1500, 100)

        st.markdown("### Loan Details")
        col3, col4 = st.columns(2)
        with col3:
            loan_amount = st.number_input("Loan Amount ($)", 50000, 5000000, 350000, 5000)
            loan_purpose = st.selectbox("Loan Purpose", ["Purchase", "Refinance", "Cash-out Refinance",
                                                          "Investment Property"])
            loan_term = st.selectbox("Loan Term (years)", [15, 20, 30], index=2)
        with col4:
            property_value = st.number_input("Property Value ($)", 50000, 10000000, 450000, 5000)
            property_type = st.selectbox("Property Type",
                ["Single Family", "Condo", "Townhouse", "Multi-Family", "Investment"])
            property_address = st.text_input("Property Address", "123 Main St, Austin, TX 78701")

        geographic_risk = st.slider("Geographic Risk Factor", 0.0, 1.0, 0.3, 0.05,
                                     help="0 = low risk area, 1 = high risk area")

        submitted = st.form_submit_button("🚀 Submit Application & Run Pipeline", use_container_width=True)

    if submitted:
        app_data = {
            "applicationId": f"APP-{str(uuid.uuid4())[:6].upper()}",
            "firstName": first_name,
            "lastName": last_name,
            "creditScore": credit_score,
            "annualIncome": annual_income,
            "employmentStatus": employment_status,
            "employmentYears": employment_years,
            "monthlyDebts": monthly_debts,
            "loanAmount": loan_amount,
            "propertyValue": property_value,
            "propertyType": property_type,
            "propertyAddress": property_address,
            "loanPurpose": loan_purpose,
            "loanTerm": loan_term,
            "geographicRisk": geographic_risk,
        }
        _run_and_display(app_data)


def _run_and_display(app_data: dict):
    settings = st.session_state.get("llm_settings", {})

    st.markdown("---")
    st.markdown(f"### Pipeline Execution — `{app_data['applicationId']}`")
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)

    progress_bar = st.progress(0, text="Initializing pipeline...")
    status_container = st.empty()
    agent_cols = st.columns(7)
    agent_ids = list(AGENTS.keys())
    agent_placeholders = {aid: col.empty() for aid, col in zip(agent_ids, agent_cols)}

    # Render all agents as pending
    for aid, ph in agent_placeholders.items():
        ph.markdown(f"""
        <div style="text-align:center; padding: 8px; border: 1px solid #e5e7eb; border-radius: 4px;">
            <div style="font-size:0.65rem; font-weight:600; color:#6b7280;">{AGENTS[aid]['name'].replace(' ', '<br>')}</div>
            <div class="badge-pending" style="margin-top:4px;">Pending</div>
        </div>
        """, unsafe_allow_html=True)

    def progress_callback(step: int, total: int, message: str):
        progress_bar.progress(step / total, text=message)
        # Mark current agent as running
        current_agent_id = agent_ids[step - 1] if step - 1 < len(agent_ids) else None
        if current_agent_id:
            agent_placeholders[current_agent_id].markdown(f"""
            <div style="text-align:center; padding: 8px; border: 2px solid #d97706; border-radius: 4px; background:#fef9c3;">
                <div style="font-size:0.65rem; font-weight:600; color:#92400e;">{AGENTS[current_agent_id]['name'].replace(' ', '<br>')}</div>
                <div class="badge-running" style="margin-top:4px;">Running</div>
            </div>
            """, unsafe_allow_html=True)

    run = run_pipeline(app_data, settings, progress_callback=progress_callback)

    # Update agent cards with final status
    for ar in run.agent_results:
        color = "#dcfce7" if ar.status == "completed" else "#fee2e2"
        border = "#16a34a" if ar.status == "completed" else "#dc2626"
        badge = "completed" if ar.status == "completed" else "failed"
        agent_placeholders[ar.agent_id].markdown(f"""
        <div style="text-align:center; padding: 8px; border: 2px solid {border}; border-radius: 4px; background:{color};">
            <div style="font-size:0.65rem; font-weight:600; color:#0a0a0a;">{ar.agent_name.replace(' ', '<br>')}</div>
            <div class="badge-{badge}" style="margin-top:4px;">{ar.duration_ms}ms</div>
        </div>
        """, unsafe_allow_html=True)

    progress_bar.progress(1.0, text="Pipeline complete!")

    # Store run
    st.session_state.pipeline_runs.append(run)
    st.session_state.active_run = run

    # Show decision
    _render_decision(run)


def _render_decision(run):
    if not run.final_decision:
        st.error("Pipeline failed to produce a decision.")
        return

    d = run.final_decision
    decision = d.get("decision", "Unknown")
    css_class = {
        "Approved": "decision-approved",
        "Conditional Approval": "decision-conditional",
        "Denied": "decision-denied",
    }.get(decision, "decision-conditional")

    icon = {"Approved": "✅", "Conditional Approval": "🔶", "Denied": "❌"}.get(decision, "⚪")

    st.markdown(f"""
    <div class="{css_class}" style="margin-top: 1.5rem;">
        <div style="font-size: 1.5rem; font-weight: 900;">{icon} {decision}</div>
        <div style="font-size: 0.9rem; margin-top: 0.5rem; color: #374151;">{d.get('decisionSummary', '')}</div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Interest Rate", f"{d.get('interestRate', '—')}%")
    with col2:
        st.metric("Approved Amount", f"${d.get('approvedAmount', 0):,.0f}")
    with col3:
        st.metric("Confidence", f"{d.get('decisionConfidence', 0)}%")

    if d.get("conditions"):
        st.markdown("**Conditions:**")
        for c in d["conditions"]:
            st.markdown(f"- {c}")

    # Protocol tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Audit Trail", "📡 SLIM Messages", "📈 OTel Trace", "🔍 Agent Discovery"])

    with tab1:
        _render_audit_trail(run)
    with tab2:
        _render_slim_messages(run)
    with tab3:
        _render_otel_trace(run)
    with tab4:
        _render_dir_events(run)


def _render_audit_trail(run):
    import json
    from datetime import datetime
    st.markdown("#### Complete Audit Trail")
    for ar in run.agent_results:
        ts = datetime.fromtimestamp(ar.started_at).strftime("%H:%M:%S.%f")[:-3]
        with st.expander(f"[{ts}] {ar.agent_name} — {ar.status.upper()} ({ar.duration_ms}ms)"):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Input**")
                st.json(ar.input_data)
            with col2:
                st.markdown("**Output**")
                st.json(ar.output_data)


def _render_slim_messages(run):
    import json
    st.markdown("#### SLIM Inter-Agent Message Bus")
    st.caption("Secure Low-Latency Interactive Messaging — full protocol envelopes")
    for i, msg in enumerate(run.slim_messages):
        direction = "→" if msg["message_type"] == "REQUEST" else "←"
        label = f"{direction} {msg['from']['agent_id']} → {msg['to']['agent_id']} [{msg['message_type']}]"
        with st.expander(label):
            # Show envelope without full payload data to keep it readable
            display = {k: v for k, v in msg.items() if k != "payload"}
            display["payload"] = {
                "schema": msg["payload"]["schema"],
                "size_bytes": msg["payload"]["size_bytes"],
                "data": "(truncated for display)",
            }
            st.markdown(f'<div class="slim-envelope">{json.dumps(display, indent=2)}</div>',
                        unsafe_allow_html=True)
            if st.checkbox("Show full payload", key=f"slim_payload_{i}"):
                st.json(msg["payload"]["data"])


def _render_otel_trace(run):
    import plotly.graph_objects as go
    st.markdown("#### OpenTelemetry Trace Waterfall")
    st.caption(f"Trace ID: `{run.trace_id}`")

    spans = [s for s in run.otel_spans if s.get("duration_ms")]
    if not spans:
        st.info("No completed spans yet.")
        return

    min_start = min(s["start_time_ms"] for s in spans)
    max_end = max(s.get("end_time_ms", s["start_time_ms"]) for s in spans)
    total_duration = max(max_end - min_start, 1)

    fig = go.Figure()
    colors = {"OK": "#16a34a", "ERROR": "#dc2626", "UNSET": "#6b7280"}

    for i, span in enumerate(spans):
        start_pct = (span["start_time_ms"] - min_start) / total_duration * 100
        dur_pct = span["duration_ms"] / total_duration * 100
        color = colors.get(span["status"], "#6b7280")

        fig.add_trace(go.Bar(
            name=span["agent_id"],
            x=[span["duration_ms"]],
            y=[span["name"]],
            orientation="h",
            base=[span["start_time_ms"] - min_start],
            marker_color=color,
            text=f"{span['duration_ms']}ms",
            textposition="inside",
            hovertemplate=(
                f"<b>{span['name']}</b><br>"
                f"Duration: {span['duration_ms']}ms<br>"
                f"Status: {span['status']}<br>"
                f"Span ID: {span['span_id']}<extra></extra>"
            ),
        ))

    fig.update_layout(
        barmode="overlay",
        height=350,
        showlegend=False,
        xaxis_title="Time (ms from pipeline start)",
        paper_bgcolor="white",
        plot_bgcolor="#f9fafb",
        margin=dict(t=10, b=40, l=10, r=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Span table
    st.markdown("**Span Details**")
    rows = []
    for s in spans:
        rows.append({
            "Agent": s["agent_id"],
            "Span ID": s["span_id"][:8],
            "Parent": (s.get("parent_span_id") or "root")[:8],
            "Duration (ms)": s["duration_ms"],
            "Status": s["status"],
        })
    import pandas as pd
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_dir_events(run):
    import pandas as pd
    st.markdown("#### Agent Directory — Discovery Events")
    st.caption("OASF-based capability discovery and DID identity resolution")
    if not run.dir_events:
        st.info("No directory events recorded.")
        return

    rows = []
    for e in run.dir_events:
        rows.append({
            "Event": e["event_type"],
            "Agent": e["agent_id"],
            "DID": e["agent_did"][:40] + "...",
            "Capability": e["query_capability"],
            "Matches": e["matched_agents"],
            "Identity Verified": "✅" if e["identity_verified"] else "❌",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
