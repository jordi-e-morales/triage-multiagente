"""
AGNTCY Mortgage Underwriting Demo — Streamlit Frontend
"""
import streamlit as st

st.set_page_config(
    page_title="Multi-agentes bajo control",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Global CSS (International Typographic Style) ─────────────────────────────
st.markdown("""
<style>
/* Sin @import de Google Fonts: el día del evento nada depende de internet.
   Si Inter está instalada en la máquina se usa; si no, la fuente del sistema. */
html, body, [class*="css"] {
    font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: #0a0a0a !important;
    border-right: 3px solid #E31E24 !important;
}
section[data-testid="stSidebar"] * { color: #ffffff !important; }
section[data-testid="stSidebar"] .stRadio label { font-size: 0.9rem; font-weight: 500; }

/* Main background */
.main .block-container { background: #ffffff; padding-top: 1.5rem; }

/* Headers */
h1 { font-weight: 900 !important; letter-spacing: -0.03em !important; color: #0a0a0a !important; }
h2 { font-weight: 700 !important; letter-spacing: -0.02em !important; color: #0a0a0a !important; }
h3 { font-weight: 600 !important; color: #0a0a0a !important; }

/* Red accent divider */
.red-bar { height: 4px; background: #E31E24; margin: 0.5rem 0 1.5rem 0; border-radius: 2px; }
.red-dot { display: inline-block; width: 10px; height: 10px; background: #E31E24; border-radius: 0; margin-right: 8px; }

/* Metric cards */
.metric-card {
    background: #f8f8f8;
    border-left: 4px solid #E31E24;
    padding: 1rem 1.2rem;
    margin-bottom: 0.5rem;
}

/* Agent status badges */
.badge-completed { background: #dcfce7; color: #166534; padding: 2px 10px; border-radius: 3px; font-size: 0.75rem; font-weight: 600; }
.badge-running   { background: #fef9c3; color: #854d0e; padding: 2px 10px; border-radius: 3px; font-size: 0.75rem; font-weight: 600; }
.badge-failed    { background: #fee2e2; color: #991b1b; padding: 2px 10px; border-radius: 3px; font-size: 0.75rem; font-weight: 600; }
.badge-pending   { background: #f3f4f6; color: #6b7280; padding: 2px 10px; border-radius: 3px; font-size: 0.75rem; font-weight: 600; }

/* Decision banners */
.decision-approved    { background: #dcfce7; border-left: 6px solid #16a34a; padding: 1.2rem 1.5rem; }
.decision-conditional { background: #fef9c3; border-left: 6px solid #d97706; padding: 1.2rem 1.5rem; }
.decision-denied      { background: #fee2e2; border-left: 6px solid #dc2626; padding: 1.2rem 1.5rem; }

/* SLIM message envelope */
.slim-envelope {
    background: #0a0a0a;
    color: #00ff88;
    font-family: 'Courier New', monospace;
    font-size: 0.75rem;
    padding: 1rem;
    border-radius: 4px;
    overflow-x: auto;
}

/* OTel span bar */
.otel-bar-container { background: #f3f4f6; border-radius: 3px; height: 20px; position: relative; }
.otel-bar { background: #E31E24; height: 100%; border-radius: 3px; }

/* Buttons */
.stButton > button {
    background: #E31E24 !important;
    color: white !important;
    border: none !important;
    font-weight: 600 !important;
    border-radius: 3px !important;
}
.stButton > button:hover { background: #b91c1c !important; }

/* ─── Deliberación (triage de alertas) ─── */
.etiqueta-sintetico { background: #0a0a0a; color: #fff; padding: 2px 8px; font-size: 0.7rem;
                      font-weight: 700; letter-spacing: 0.08em; border-radius: 3px; margin-right: 6px; }
/* Hechos: lo que escribió un tercero se ve distinto de lo que produjo el sistema. */
.hecho-interno { border-left: 4px solid #6b7280; background: #f8f8f8; padding: 6px 10px; margin: 4px 0; }
.hecho-externo { border-left: 4px solid #d97706; background: #fffbeb; padding: 6px 10px; margin: 4px 0; }
.marca-externo { background: #d97706; color: #fff; font-size: 0.65rem; font-weight: 700;
                 padding: 1px 6px; border-radius: 3px; margin-right: 6px; }
.cita { font-family: 'Courier New', monospace; font-size: 0.75rem; color: #6b7280; }
.tarjeta-agente { border: 1px solid #e5e7eb; border-left-width: 6px; padding: 10px 14px; margin: 10px 0; background: #fff; }
.tarjeta-investigador { border-left-color: #E31E24; }
.tarjeta-defensor { border-left-color: #2563eb; }
.tarjeta-titulo { font-weight: 700; font-size: 0.95rem; }
.tarjeta-tesis { font-size: 1.05rem; margin: 6px 0; }
.tarjeta-meta { font-size: 0.7rem; color: #6b7280; }
.rebate { font-size: 0.8rem; color: #374151; font-style: italic; }
.salto-lateral { background: #ede9fe; color: #5b21b6; font-size: 0.7rem; font-weight: 600;
                 padding: 1px 8px; border-radius: 3px; margin-left: 6px; }
.paso-omitido { background: #fee2e2; color: #991b1b; padding: 6px 10px; margin: 6px 0; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


# ─── Páginas del demo previo de hipotecas ─────────────────────────────────────
# Cuatro de esas páginas importan agents.pipeline / ml.models, que requieren
# torch y xgboost (más de 1 GB). La imagen de la UI de la demo no los trae,
# así que esas páginas solo aparecen donde esos paquetes están instalados.
import importlib.util

HIPOTECAS_DISPONIBLE = all(importlib.util.find_spec(m) for m in ("torch", "xgboost"))


# ─── Session state defaults ───────────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "Deliberación"
if "pipeline_runs" not in st.session_state:
    st.session_state.pipeline_runs = []
if "current_run" not in st.session_state:
    st.session_state.current_run = None
if "llm_settings" not in st.session_state:
    st.session_state.llm_settings = {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "",
        "ollama_url": "http://localhost:11434",
        "temperature": 0.1,
        "max_tokens": 2048,
    }


# ─── Sidebar navigation ───────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding: 1rem 0 0.5rem 0;">
        <div style="font-size: 1.4rem; font-weight: 900; letter-spacing: -0.03em; color: #fff;">
            AGNTCY
        </div>
        <div style="height: 3px; background: #E31E24; margin: 6px 0 4px 0;"></div>
        <div style="font-size: 0.7rem; color: #aaa; letter-spacing: 0.1em; text-transform: uppercase;">
            Multi-agentes bajo control
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    pages = ["🧭 Deliberación"]
    if HIPOTECAS_DISPONIBLE:
        pages += [
            "📊 Dashboard",
            "📝 New Application",
            "🗂️ Applications",
            "🚀 Test Scenarios",
            "🤖 Agent Directory",
            "⚙️ Settings",
        ]
    # Página Admin (apuntes de contenedores y modelos). Se oculta en el stand
    # con MOSTRAR_ADMIN=0.
    from servicios.config import admin_visible
    if admin_visible():
        pages.append("🛠️ Admin")
    page_labels = {p.split(" ", 1)[1]: p for p in pages}
    page_keys = [p.split(" ", 1)[1] for p in pages]

    selected = st.radio("Navigation", page_keys, index=page_keys.index(
        st.session_state.page if st.session_state.page in page_keys else "Deliberación"
    ), label_visibility="collapsed")
    st.session_state.page = selected

    st.markdown("---")
    # Estado REAL de la demo. Antes esta lista decía "SLIM Protocol, OASF,
    # OpenTelemetry, Agent Directory" como si estuvieran en uso, y en esta
    # versión los componentes hablan HTTP. Regla de CLAUDE.md: no afirmar lo
    # que no está. ● = en uso y verificado · ○ = pendiente.
    st.markdown("""
    <div style="font-size: 0.65rem; color: #666; padding: 0.5rem 0;">
        <div style="margin-bottom: 4px;"><span style="color:#E31E24;">●</span> Un pod por componente (kind)</div>
        <div style="margin-bottom: 4px;"><span style="color:#E31E24;">●</span> HTTP entre pods con X-Trace-Id</div>
        <div style="margin-bottom: 4px;"><span style="color:#E31E24;">●</span> Inferencia local (Ollama, CPU)</div>
        <div style="margin-bottom: 4px;"><span style="color:#E31E24;">●</span> Cilium + Hubble (visibilidad)</div>
        <div style="margin-bottom: 4px; color:#555;">○ Políticas L7 y Tetragon · pendiente</div>
        <div style="color:#555;">○ Identidad verificada (mTLS) · pendiente</div>
    </div>
    """, unsafe_allow_html=True)


# ─── Page routing ─────────────────────────────────────────────────────────────
page = st.session_state.page

if page == "Deliberación":
    from pages.deliberacion import render
    render()
elif page == "Dashboard":
    from pages.dashboard import render
    render()
elif page == "New Application":
    from pages.apply import render
    render()
elif page == "Applications":
    from pages.applications import render
    render()
elif page == "Test Scenarios":
    from pages.scenarios import render
    render()
elif page == "Agent Directory":
    from pages.agent_directory import render
    render()
elif page == "Settings":
    from pages.settings import render
    render()
elif page == "Admin":
    from pages.admin import render
    render()
