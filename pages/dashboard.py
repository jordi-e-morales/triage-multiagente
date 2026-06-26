"""Dashboard page — key metrics and recent runs."""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime


def render():
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)
    st.markdown("# AGNTCY Mortgage Underwriting")
    st.markdown("**Multi-Agent Orchestration Demo** — Internet of Agents Framework")
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)

    runs = st.session_state.get("pipeline_runs", [])

    # ── Metrics ──────────────────────────────────────────────────────────────
    total = len(runs)
    completed = [r for r in runs if r.status == "completed"]
    approved = [r for r in completed if r.final_decision and
                r.final_decision.get("decision", "").lower() in ["approved", "conditional approval"]]
    approval_rate = round(len(approved) / max(len(completed), 1) * 100, 1)
    avg_duration = round(
        sum((r.completed_at or r.started_at) - r.started_at for r in completed) / max(len(completed), 1), 1
    )
    avg_rate = 0.0
    rates = [r.final_decision.get("interestRate", 0) for r in completed
             if r.final_decision and r.final_decision.get("interestRate")]
    if rates:
        avg_rate = round(sum(rates) / len(rates), 2)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Applications", total)
    with col2:
        st.metric("Approval Rate", f"{approval_rate}%")
    with col3:
        st.metric("Avg Processing Time", f"{avg_duration}s")
    with col4:
        st.metric("Avg Interest Rate", f"{avg_rate}%" if avg_rate else "—")

    st.markdown("---")

    # ── Charts ───────────────────────────────────────────────────────────────
    if completed:
        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown("### Decision Distribution")
            decisions = {}
            for r in completed:
                d = r.final_decision.get("decision", "Unknown") if r.final_decision else "Unknown"
                decisions[d] = decisions.get(d, 0) + 1

            colors = {"Approved": "#16a34a", "Conditional Approval": "#d97706",
                      "Denied": "#dc2626", "Unknown": "#6b7280"}
            fig = go.Figure(go.Pie(
                labels=list(decisions.keys()),
                values=list(decisions.values()),
                marker_colors=[colors.get(k, "#6b7280") for k in decisions.keys()],
                hole=0.4,
            ))
            fig.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10),
                              showlegend=True, paper_bgcolor="white")
            st.plotly_chart(fig, use_container_width=True)

        with col_right:
            st.markdown("### Agent Performance (avg ms)")
            agent_durations: dict[str, list] = {}
            for r in completed:
                for ar in r.agent_results:
                    if ar.agent_id not in agent_durations:
                        agent_durations[ar.agent_id] = []
                    agent_durations[ar.agent_id].append(ar.duration_ms)

            if agent_durations:
                labels = [k.replace("-", " ").title() for k in agent_durations.keys()]
                values = [round(sum(v) / len(v)) for v in agent_durations.values()]
                fig2 = go.Figure(go.Bar(
                    x=values, y=labels, orientation="h",
                    marker_color="#E31E24",
                ))
                fig2.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10),
                                   paper_bgcolor="white", plot_bgcolor="white",
                                   xaxis_title="ms")
                st.plotly_chart(fig2, use_container_width=True)

    else:
        st.info("No completed pipeline runs yet. Go to **Test Scenarios** to run a demo.")

    # ── Recent runs ───────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Recent Applications")
    if runs:
        for r in reversed(runs[-10:]):
            decision = r.final_decision.get("decision", "—") if r.final_decision else "Processing..."
            duration = round((r.completed_at or r.started_at) - r.started_at, 1)
            ts = datetime.fromtimestamp(r.started_at).strftime("%H:%M:%S")
            color = {"Approved": "🟢", "Conditional Approval": "🟡", "Denied": "🔴"}.get(decision, "⚪")
            col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
            with col1:
                if st.button(f"📄 {r.application_id}", key=f"dash_{r.application_id}"):
                    st.session_state.current_run = r
                    st.session_state.page = "Applications"
                    st.rerun()
            with col2:
                st.write(f"{color} {decision}")
            with col3:
                st.write(f"{duration}s")
            with col4:
                st.write(ts)
    else:
        st.write("No applications yet.")

    # ── AGNTCY Framework overview ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### AGNTCY Framework Components Active")
    cols = st.columns(4)
    components = [
        ("🔍 Discover", "Agent Directory\n7 agents registered\nOASF v1.0 schemas"),
        ("🔗 Compose", "LangGraph Orchestration\nParallel + Sequential\nDAG execution"),
        ("🚀 Deploy", "SLIM Protocol v0.1\nMLS encryption\nDID-based identity"),
        ("📊 Evaluate", "OpenTelemetry\nPer-agent spans\nFull audit trail"),
    ]
    for col, (title, desc) in zip(cols, components):
        with col:
            st.markdown(f"**{title}**")
            st.caption(desc)
