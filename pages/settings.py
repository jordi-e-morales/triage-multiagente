"""Settings page — LLM provider configuration and ML model status."""
import streamlit as st
from ml.models import get_model_status


PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "needs_key": True,
        "env_var": "OPENAI_API_KEY",
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "models": ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307", "claude-3-opus-20240229"],
        "needs_key": True,
        "env_var": "ANTHROPIC_API_KEY",
    },
    "google": {
        "label": "Google Gemini",
        "models": ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"],
        "needs_key": True,
        "env_var": "GOOGLE_API_KEY",
    },
    "ollama": {
        "label": "Ollama (Local)",
        "models": ["llama3.2", "llama3.1", "mistral", "mixtral", "qwen2.5", "gemma2", "phi3"],
        "needs_key": False,
        "env_var": None,
    },
}


def render():
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)
    st.markdown("# Settings")
    st.markdown("Configure LLM provider, model selection, and ML model status.")
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)

    settings = st.session_state.get("llm_settings", {})

    # ── LLM Provider ──────────────────────────────────────────────────────────
    st.markdown("### LLM Provider")
    st.caption("Select the language model provider used by all agents in the pipeline.")

    provider_options = list(PROVIDERS.keys())
    provider_labels = [PROVIDERS[p]["label"] for p in provider_options]
    current_provider = settings.get("provider", "openai")
    current_idx = provider_options.index(current_provider) if current_provider in provider_options else 0

    selected_provider_label = st.radio(
        "Provider",
        provider_labels,
        index=current_idx,
        horizontal=True,
        label_visibility="collapsed",
    )
    selected_provider = provider_options[provider_labels.index(selected_provider_label)]
    provider_info = PROVIDERS[selected_provider]

    col1, col2 = st.columns(2)
    with col1:
        model_options = provider_info["models"]
        current_model = settings.get("model", model_options[0])
        if current_model not in model_options:
            current_model = model_options[0]
        selected_model = st.selectbox("Model", model_options,
                                       index=model_options.index(current_model))

    with col2:
        if provider_info["needs_key"]:
            api_key = st.text_input(
                f"API Key ({provider_info['env_var']})",
                value=settings.get("api_key", ""),
                type="password",
                help=f"Set {provider_info['env_var']} environment variable or enter here.",
            )
        else:
            api_key = ""
            ollama_url = st.text_input(
                "Ollama Base URL",
                value=settings.get("ollama_url", "http://localhost:11434"),
            )
            if st.button("Test Ollama Connection"):
                import requests
                try:
                    r = requests.get(f"{ollama_url}/api/tags", timeout=3)
                    if r.status_code == 200:
                        models = [m["name"] for m in r.json().get("models", [])]
                        st.success(f"✅ Connected! Available models: {', '.join(models[:5]) or 'none pulled yet'}")
                    else:
                        st.error(f"❌ HTTP {r.status_code}")
                except Exception as e:
                    st.error(f"❌ Cannot connect: {e}")

    # Advanced settings
    with st.expander("Advanced Settings"):
        temperature = st.slider("Temperature", 0.0, 1.0,
                                 settings.get("temperature", 0.1), 0.05)
        max_tokens = st.number_input("Max Tokens", 256, 8192,
                                      settings.get("max_tokens", 2048), 256)

    if st.button("💾 Save LLM Settings", type="primary"):
        new_settings = {
            "provider": selected_provider,
            "model": selected_model,
            "api_key": api_key,
            "ollama_url": settings.get("ollama_url", "http://localhost:11434")
                          if selected_provider == "ollama" else settings.get("ollama_url", "http://localhost:11434"),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if selected_provider == "ollama":
            new_settings["ollama_url"] = ollama_url
        st.session_state.llm_settings = new_settings
        st.success(f"✅ Saved — using **{provider_info['label']} / {selected_model}**")

    # ── Current active provider banner ────────────────────────────────────────
    st.markdown("---")
    active = PROVIDERS.get(settings.get("provider", "openai"), {})
    st.markdown(f"""
    <div style="background:#f0fdf4; border-left:4px solid #16a34a; padding:0.8rem 1rem;">
        <strong>Active Provider:</strong> {active.get('label', '—')} / {settings.get('model', '—')}<br>
        <span style="font-size:0.8rem; color:#374151;">Temperature: {settings.get('temperature', 0.1)} | Max tokens: {settings.get('max_tokens', 2048)}</span>
    </div>
    """, unsafe_allow_html=True)

    # ── ML Model Status ───────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### ML Inference Models")
    st.caption("Real ML models trained on synthetic mortgage data. Loaded in-process — no separate server needed.")

    if st.button("🔄 Refresh ML Status"):
        st.rerun()

    try:
        ml_status = get_model_status()
    except Exception as e:
        ml_status = {}
        st.warning(f"Could not load ML status: {e}")

    col1, col2 = st.columns(2)
    with col1:
        xgb_ok = ml_status.get("xgboost_loaded", False)
        st.markdown(f"""
        <div style="background:{'#dcfce7' if xgb_ok else '#fef9c3'}; border-left:4px solid {'#16a34a' if xgb_ok else '#d97706'}; padding:1rem;">
            <div style="font-weight:700;">XGBoost Credit Risk Model</div>
            <div style="font-size:0.8rem; margin-top:4px;">
                Status: {'✅ Loaded' if xgb_ok else '⏳ Will load on first pipeline run'}<br>
                AUC: {ml_status.get('xgb_auc', 'N/A')}<br>
                Training data: 50,000 synthetic mortgage records<br>
                Features: credit score, DTI, LTV, employment, income
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        gnn_ok = ml_status.get("gnn_loaded", False)
        st.markdown(f"""
        <div style="background:{'#dcfce7' if gnn_ok else '#fef9c3'}; border-left:4px solid {'#16a34a' if gnn_ok else '#d97706'}; padding:1rem;">
            <div style="font-weight:700;">GNN Fraud Detection Model</div>
            <div style="font-size:0.8rem; margin-top:4px;">
                Status: {'✅ Loaded' if gnn_ok else '⏳ Will load on first pipeline run'}<br>
                AUC: {ml_status.get('gnn_auc', 'N/A')}<br>
                Architecture: 2-layer Graph Convolutional Network<br>
                Features: transaction graph, geographic risk, network patterns
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("""
    <div style="background:#f8f8f8; border-left:4px solid #E31E24; padding:0.8rem 1rem; margin-top:1rem;">
        <strong>Note:</strong> ML models are loaded in-process and persist for the duration of the Streamlit session.
        They are automatically trained on first use using synthetic data. No GPU required.
    </div>
    """, unsafe_allow_html=True)

    # ── Environment variable guide ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Environment Variables")
    st.markdown("Set these in your shell or `.env` file for automatic key loading:")
    st.code("""
# OpenAI
export OPENAI_API_KEY=sk-...

# Anthropic
export ANTHROPIC_API_KEY=sk-ant-...

# Google Gemini
export GOOGLE_API_KEY=AIza...

# Ollama (local — no key needed)
export OLLAMA_BASE_URL=http://localhost:11434
    """, language="bash")
