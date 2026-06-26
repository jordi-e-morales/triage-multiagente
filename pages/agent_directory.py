"""Agent Directory page — OASF-registered agents."""
import streamlit as st
import json
from agents.pipeline import AGENTS
from ml.models import get_model_status


def render():
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)
    st.markdown("# Agent Directory")
    st.markdown("AGNTCY Agent Directory — OASF v1.0 registered agents with DID identity.")
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)

    ml_status = {}
    try:
        ml_status = get_model_status()
    except Exception:
        pass

    # ML model status banner
    col1, col2 = st.columns(2)
    with col1:
        xgb_ok = ml_status.get("xgboost_loaded", False)
        st.markdown(f"""
        <div style="background:{'#dcfce7' if xgb_ok else '#fee2e2'}; border-left:4px solid {'#16a34a' if xgb_ok else '#dc2626'}; padding:0.8rem 1rem; margin-bottom:0.5rem;">
            <strong>XGBoost Credit Risk Model</strong><br>
            <span style="font-size:0.8rem;">{'✅ Loaded — AUC ' + str(ml_status.get('xgb_auc', '—')) if xgb_ok else '⚠️ Not loaded — run the app to train'}</span>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        gnn_ok = ml_status.get("gnn_loaded", False)
        st.markdown(f"""
        <div style="background:{'#dcfce7' if gnn_ok else '#fee2e2'}; border-left:4px solid {'#16a34a' if gnn_ok else '#dc2626'}; padding:0.8rem 1rem; margin-bottom:0.5rem;">
            <strong>GNN Fraud Detection Model</strong><br>
            <span style="font-size:0.8rem;">{'✅ Loaded — AUC ' + str(ml_status.get('gnn_auc', '—')) if gnn_ok else '⚠️ Not loaded — run the app to train'}</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(f"**{len(AGENTS)} agents registered**")

    OASF_META = {
        "application-processor": {
            "oasf_version": "1.0", "agent_type": "processor",
            "execution_mode": "sequential", "pipeline_stage": "intake",
            "sla_ms": 5000, "auth_required": True,
            "ml_models": [],
        },
        "credit-analyzer": {
            "oasf_version": "1.0", "agent_type": "analyzer",
            "execution_mode": "parallel", "pipeline_stage": "parallel_analysis",
            "sla_ms": 15000, "auth_required": True,
            "ml_models": ["XGBoost Credit Risk (AUC 0.786)"],
        },
        "collateral-valuator": {
            "oasf_version": "1.0", "agent_type": "valuator",
            "execution_mode": "parallel", "pipeline_stage": "parallel_analysis",
            "sla_ms": 12000, "auth_required": True,
            "ml_models": [],
        },
        "compliance-checker": {
            "oasf_version": "1.0", "agent_type": "compliance",
            "execution_mode": "parallel", "pipeline_stage": "parallel_analysis",
            "sla_ms": 10000, "auth_required": True,
            "ml_models": ["GNN Fraud Detection (AUC 0.868)"],
        },
        "risk-scorer": {
            "oasf_version": "1.0", "agent_type": "scorer",
            "execution_mode": "sequential", "pipeline_stage": "aggregation",
            "sla_ms": 8000, "auth_required": True,
            "ml_models": ["XGBoost + GNN ensemble"],
        },
        "decision-engine": {
            "oasf_version": "1.0", "agent_type": "decision",
            "execution_mode": "sequential", "pipeline_stage": "decision",
            "sla_ms": 10000, "auth_required": True,
            "ml_models": [],
        },
        "documentation-generator": {
            "oasf_version": "1.0", "agent_type": "generator",
            "execution_mode": "sequential", "pipeline_stage": "output",
            "sla_ms": 8000, "auth_required": True,
            "ml_models": [],
        },
    }

    stage_colors = {
        "intake": "#3b82f6",
        "parallel_analysis": "#8b5cf6",
        "aggregation": "#f59e0b",
        "decision": "#E31E24",
        "output": "#16a34a",
    }

    for agent_id, agent in AGENTS.items():
        meta = OASF_META.get(agent_id, {})
        stage = meta.get("pipeline_stage", "unknown")
        color = stage_colors.get(stage, "#6b7280")

        with st.expander(f"**{agent['name']}** — v{agent['version']} | Stage: {stage}", expanded=False):
            col1, col2 = st.columns([2, 1])
            with col1:
                st.markdown(f"**DID:** `{agent['did']}`")
                st.markdown(f"**Capabilities:**")
                for cap in agent["capabilities"]:
                    st.markdown(f"  - `{cap}`")
                if meta.get("ml_models"):
                    st.markdown(f"**ML Models:**")
                    for m in meta["ml_models"]:
                        st.markdown(f"  - 🤖 {m}")
            with col2:
                st.markdown(f"**OASF Version:** {meta.get('oasf_version', '—')}")
                st.markdown(f"**Agent Type:** {meta.get('agent_type', '—')}")
                st.markdown(f"**Execution:** {meta.get('execution_mode', '—')}")
                st.markdown(f"**SLA:** {meta.get('sla_ms', '—')}ms")
                st.markdown(f"**Auth Required:** {'Yes' if meta.get('auth_required') else 'No'}")

            # Raw OASF JSON
            if st.checkbox("Show OASF Schema JSON", key=f"oasf_{agent_id}"):
                oasf_doc = {
                    "oasf_version": meta.get("oasf_version", "1.0"),
                    "agent_id": agent_id,
                    "name": agent["name"],
                    "version": agent["version"],
                    "did": agent["did"],
                    "capabilities": agent["capabilities"],
                    "ml_models": meta.get("ml_models", []),
                    "execution": {
                        "mode": meta.get("execution_mode"),
                        "pipeline_stage": meta.get("pipeline_stage"),
                        "sla_ms": meta.get("sla_ms"),
                    },
                    "security": {
                        "auth_required": meta.get("auth_required"),
                        "protocol": "SLIM/0.1",
                        "identity": "DID:agntcy",
                    },
                }
                st.json(oasf_doc)

    # Pipeline topology diagram
    st.markdown("---")
    st.markdown("### Pipeline Topology")
    st.markdown("""
    ```
    ┌─────────────────────────────────────────────────────────────────────┐
    │                    AGNTCY Mortgage Pipeline                          │
    │                                                                       │
    │  [Application Processor]                                              │
    │          │                                                            │
    │          ▼  (parallel via SLIM pub-sub)                               │
    │  ┌───────┴──────────────────────────┐                                │
    │  ▼                ▼                 ▼                                 │
    │ [Credit Analyzer] [Collateral   [Compliance                          │
    │  XGBoost ML        Valuator]     Checker]                            │
    │                                  GNN ML                              │
    │  └───────────────┬────────────────┘                                  │
    │                  ▼                                                    │
    │           [Risk Scorer]  ← ML Ensemble (XGBoost + GNN)               │
    │                  │                                                    │
    │                  ▼                                                    │
    │          [Decision Engine]                                            │
    │                  │                                                    │
    │                  ▼                                                    │
    │      [Documentation Generator]                                        │
    └─────────────────────────────────────────────────────────────────────┘
    ```
    """)
