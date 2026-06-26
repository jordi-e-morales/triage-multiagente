"""Test Scenarios page — one-click demo runs."""
import streamlit as st
from data.scenarios import SCENARIOS


def render():
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)
    st.markdown("# Test Scenarios")
    st.markdown("One-click demo runs covering the full decision spectrum.")
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)

    settings = st.session_state.get("llm_settings", {})

    for key, scenario in SCENARIOS.items():
        with st.container():
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"### {scenario['icon']} {scenario['label']}")
                st.caption(scenario["description"])

                # Show key data points
                data = scenario["data"]
                metrics_cols = st.columns(5)
                metrics_cols[0].metric("Credit Score", data.get("creditScore", "—"))
                metrics_cols[1].metric("Income", f"${data.get('annualIncome', 0):,.0f}")
                metrics_cols[2].metric("Loan", f"${data.get('loanAmount', 0):,.0f}")
                metrics_cols[3].metric("Property", f"${data.get('propertyValue', 0):,.0f}")
                ltv = round(data.get("loanAmount", 0) / max(data.get("propertyValue", 1), 1) * 100, 1)
                metrics_cols[4].metric("LTV", f"{ltv}%")

            with col2:
                st.markdown(f"**Expected:** {scenario['expected_decision']}")
                if st.button(f"▶ Run Scenario", key=f"run_{key}", use_container_width=True):
                    _run_scenario(scenario, settings)

            st.divider()


def _run_scenario(scenario: dict, settings: dict):
    from agents.pipeline import run_pipeline, AGENTS
    import uuid

    app_data = dict(scenario["data"])
    app_data["applicationId"] = f"APP-{str(uuid.uuid4())[:6].upper()}"

    st.markdown(f"---")
    st.markdown(f"### ▶ Running: {scenario['icon']} {scenario['label']}")
    st.markdown(f"Application ID: `{app_data['applicationId']}`")

    agent_ids = list(AGENTS.keys())
    progress_bar = st.progress(0, text="Initializing...")
    agent_cols = st.columns(7)
    agent_placeholders = {aid: col.empty() for aid, col in zip(agent_ids, agent_cols)}

    for aid, ph in agent_placeholders.items():
        ph.markdown(f"""
        <div style="text-align:center; padding:6px; border:1px solid #e5e7eb; border-radius:4px;">
            <div style="font-size:0.6rem; font-weight:600; color:#6b7280;">{AGENTS[aid]['name'].replace(' ', '<br>')}</div>
            <div style="font-size:0.65rem; color:#9ca3af; margin-top:2px;">Pending</div>
        </div>
        """, unsafe_allow_html=True)

    def progress_callback(step, total, message):
        progress_bar.progress(step / total, text=message)
        current_aid = agent_ids[step - 1] if step - 1 < len(agent_ids) else None
        if current_aid:
            agent_placeholders[current_aid].markdown(f"""
            <div style="text-align:center; padding:6px; border:2px solid #d97706; border-radius:4px; background:#fef9c3;">
                <div style="font-size:0.6rem; font-weight:600; color:#92400e;">{AGENTS[current_aid]['name'].replace(' ', '<br>')}</div>
                <div style="font-size:0.65rem; color:#d97706; margin-top:2px;">Running...</div>
            </div>
            """, unsafe_allow_html=True)

    run = run_pipeline(app_data, settings, progress_callback=progress_callback)

    for ar in run.agent_results:
        color = "#dcfce7" if ar.status == "completed" else "#fee2e2"
        border = "#16a34a" if ar.status == "completed" else "#dc2626"
        agent_placeholders[ar.agent_id].markdown(f"""
        <div style="text-align:center; padding:6px; border:2px solid {border}; border-radius:4px; background:{color};">
            <div style="font-size:0.6rem; font-weight:600; color:#0a0a0a;">{ar.agent_name.replace(' ', '<br>')}</div>
            <div style="font-size:0.65rem; color:{border}; margin-top:2px;">{ar.duration_ms}ms</div>
        </div>
        """, unsafe_allow_html=True)

    progress_bar.progress(1.0, text="Complete!")
    st.session_state.pipeline_runs.append(run)

    # Decision banner
    if run.final_decision:
        d = run.final_decision
        decision = d.get("decision", "Unknown")
        icon = {"Approved": "✅", "Conditional Approval": "🔶", "Denied": "❌"}.get(decision, "⚪")
        css = {"Approved": "decision-approved", "Conditional Approval": "decision-conditional",
               "Denied": "decision-denied"}.get(decision, "decision-conditional")
        st.markdown(f"""
        <div class="{css}" style="margin-top:1rem;">
            <div style="font-size:1.3rem; font-weight:900;">{icon} {decision}</div>
            <div style="font-size:0.85rem; margin-top:0.4rem;">{d.get('decisionSummary', '')}</div>
        </div>
        """, unsafe_allow_html=True)

        col1, col2, col3 = st.columns(3)
        col1.metric("Interest Rate", f"{d.get('interestRate', '—')}%")
        col2.metric("Approved Amount", f"${d.get('approvedAmount', 0):,.0f}")
        col3.metric("Confidence", f"{d.get('decisionConfidence', 0)}%")

        # Protocol tabs
        tab1, tab2, tab3 = st.tabs(["📡 SLIM Messages", "📈 OTel Trace", "🔍 Agent Discovery"])
        with tab1:
            from pages.apply import _render_slim_messages
            _render_slim_messages(run)
        with tab2:
            from pages.apply import _render_otel_trace
            _render_otel_trace(run)
        with tab3:
            from pages.apply import _render_dir_events
            _render_dir_events(run)

        if st.button("View in Applications", key=f"view_{run.application_id}"):
            st.session_state.current_run = run
            st.session_state.page = "Applications"
            st.rerun()
