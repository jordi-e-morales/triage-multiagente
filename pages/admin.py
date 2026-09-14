"""
Página Admin — a dónde apunta cada componente y cada modelo, y si responden.

Solo lectura a propósito: muestra los valores y los prueba, pero no los
cambia. Para cambiar un apunte se edita deploy/k8s/endpoints.yaml y se aplica
con kubectl (ver servicios/config.py para el porqué).
"""
import pandas as pd
import streamlit as st

from servicios.config import modelos, servicios
from servicios.verificar import verificar_modelo, verificar_servicio


def render():
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)
    st.markdown("# Admin")
    st.markdown("Apuntes de componentes y modelos. Solo lectura.")
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)

    # ── Configuración actual ────────────────────────────────────────────────
    st.markdown("### Componentes")
    st.dataframe(
        pd.DataFrame([{"Componente": s.nombre, "URL": s.url, "Variable": s.variable} for s in servicios()]),
        use_container_width=True, hide_index=True,
    )

    st.markdown("### Modelos")
    st.dataframe(
        pd.DataFrame([{
            "Rol": m.rol, "Usado por": m.usado_por, "URL": m.url, "Modelo": m.modelo,
            "Variables": f"{m.variable_url}, {m.variable_modelo}",
        } for m in modelos()]),
        use_container_width=True, hide_index=True,
    )

    # ── Prueba de conectividad ──────────────────────────────────────────────
    st.markdown("### Conectividad")
    st.caption("Hace GET a /salud de cada componente y pregunta a cada servidor de modelos qué tiene cargado.")

    if st.button("Probar ahora"):
        resultados = []
        with st.spinner("Probando..."):
            resultados += [verificar_servicio(s) for s in servicios()]
            resultados += [verificar_modelo(m) for m in modelos()]
        st.session_state.admin_resultados = resultados

    resultados = st.session_state.get("admin_resultados")
    if resultados:
        st.dataframe(
            pd.DataFrame([{
                "": "✅" if r.ok else "❌",
                "Destino": r.nombre, "URL": r.url,
                "Latencia (ms)": r.latencia_ms, "Detalle": r.detalle,
            } for r in resultados]),
            use_container_width=True, hide_index=True,
        )
        # Si un servidor responde pero no tiene el modelo, mostrar qué tiene:
        # suele ser un error de nombre ("qwen2.5:3b" vs "qwen2.5:3b-instruct").
        for r in resultados:
            if not r.ok and r.modelos_disponibles:
                st.warning(f"{r.nombre}: el servidor tiene {', '.join(r.modelos_disponibles)}")

    # ── Cómo cambiar un apunte ──────────────────────────────────────────────
    st.markdown("### Cambiar un apunte")
    st.code(
        "# 1. editar deploy/k8s/endpoints.yaml\n"
        "kubectl apply -f deploy/k8s/endpoints.yaml\n"
        "kubectl -n agentes rollout restart deploy",
        language="bash",
    )
    st.caption("El restart hace falta porque las variables de entorno se leen al arrancar el contenedor.")
