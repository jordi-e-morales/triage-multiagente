"""Applications list page — browse and inspect completed runs."""
import streamlit as st
from datetime import datetime


def render():
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)
    st.markdown("# Applications")
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)

    runs = st.session_state.get("pipeline_runs", [])

    # If a specific run is selected, show its detail
    if st.session_state.get("current_run"):
        run = st.session_state.current_run
        if st.button("← Back to Applications"):
            st.session_state.current_run = None
            st.rerun()
        st.markdown(f"### Application `{run.application_id}`")
        from pages._pipeline_view import render_pipeline_view
        render_pipeline_view(run)
        return

    if not runs:
        st.info("No applications yet. Go to **New Application** or **Test Scenarios** to get started.")
        return

    # Summary table
    st.markdown(f"**{len(runs)} applications**")
    for r in reversed(runs):
        decision = r.final_decision.get("decision", "—") if r.final_decision else "Processing..."
        duration = round((r.completed_at or r.started_at) - r.started_at, 1)
        ts = datetime.fromtimestamp(r.started_at).strftime("%Y-%m-%d %H:%M:%S")
        icon = {"Approved": "🟢", "Conditional Approval": "🟡", "Denied": "🔴"}.get(decision, "⚪")
        rate = r.final_decision.get("interestRate", "—") if r.final_decision else "—"
        amount = r.final_decision.get("approvedAmount", 0) if r.final_decision else 0

        with st.container():
            col1, col2, col3, col4, col5 = st.columns([2, 2, 1, 1, 1])
            with col1:
                if st.button(f"📄 {r.application_id}", key=f"app_{r.application_id}"):
                    st.session_state.current_run = r
                    st.rerun()
            with col2:
                st.write(f"{icon} {decision}")
            with col3:
                st.write(f"${amount:,.0f}" if amount else "—")
            with col4:
                st.write(f"{rate}%" if rate != "—" else "—")
            with col5:
                st.write(f"{duration}s")
        st.divider()

    if st.button("🗑️ Clear All Applications", type="secondary"):
        st.session_state.pipeline_runs = []
        st.session_state.current_run = None
        st.rerun()
