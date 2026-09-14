"""Shared pipeline view helper — renders a completed run.

Extendido para la demo de triage con el panel de dos carriles.
"""
import html

import streamlit as st

from protocols.carriles import alinear, resumen


def render_pipeline_view(run):
    """Render a completed pipeline run (used from Applications page)."""
    from pages.apply import _render_decision
    _render_decision(run)


# ─── Panel de dos carriles ────────────────────────────────────────────────────

def _e(texto) -> str:
    return html.escape(str(texto))


def _celda_llamada(ll: dict | None) -> str:
    if not ll:
        return "<div class='carril-vacio'>—</div>"
    estado = ll.get("estado_http")
    clase = "carril-llamada" if estado and estado < 400 else "carril-llamada carril-error"
    return (f"<div class='{clase}'><b>{_e(ll['origen'])} → {_e(ll['destino'])}</b> "
            f"<span class='cita'>{_e(ll.get('metodo', 'POST'))} {_e(ll['ruta'])}</span><br>"
            f"<span class='cita'>trace {_e((ll.get('trace_id') or 'sin traza')[:12])} · "
            f"HTTP {_e(estado if estado is not None else 'sin respuesta')}</span></div>")


def _celda_evento(ev: dict | None, huerfano: bool = False) -> str:
    if not ev:
        return "<div class='carril-vacio'>—</div>"
    clase = "carril-evento carril-alarma" if huerfano else "carril-evento"
    etiqueta = "<span class='marca-alarma'>SIN CONTRAPARTE</span>" if huerfano else ""
    traza = ev.get("trace_id") or "sin traza"
    return (f"<div class='{clase}'>{etiqueta}<b>{_e(ev['verdict'])}</b> "
            f"<span class='cita'>{_e(ev['layer'])} · {_e(ev['source'])}</span><br>"
            f"{_e(ev['action'])}<br><span class='cita'>trace {_e(traza[:12])}</span></div>")


def render_dos_carriles(llamadas: list[dict], eventos: list[dict], nota_fuente_derecha: str | None = None):
    """
    Dos carriles en el mismo eje de tiempo.
    Izquierda: lo que los componentes declaran. Derecha: lo que vio la red.
    Se alinean por traza (protocols/carriles.py), no por hora.
    """
    filas = alinear(llamadas, eventos)
    cuenta = resumen(filas)
    st.markdown("#### Dos carriles: lo que dicen los agentes · lo que vio la red")
    st.caption(f"{cuenta['par']} emparejados por traza · {cuenta['sin_evento']} llamadas sin evento de red · "
               f"{cuenta['huerfano']} eventos sin contraparte · {cuenta['l34']} flujos L3/L4")
    if nota_fuente_derecha:
        st.info(nota_fuente_derecha)

    principales = [f for f in filas if f["tipo"] != "l34"]
    partes = ["<div class='carriles'>",
              "<div class='carril-titulo'>Lo que dicen los componentes</div>",
              "<div class='carril-titulo'>Lo que vio la red</div>"]
    for f in principales:
        partes.append(_celda_llamada(f["llamada"]))
        partes.append(_celda_evento(f["evento"], huerfano=f["tipo"] == "huerfano"))
    partes.append("</div>")
    st.markdown("".join(partes), unsafe_allow_html=True)

    l34 = [f["evento"] for f in filas if f["tipo"] == "l34"]
    if l34:
        with st.expander(f"Flujos de capa 3/4 ({len(l34)}): sin encabezados, no se alinean por traza"):
            st.markdown("".join(_celda_evento(ev) for ev in l34), unsafe_allow_html=True)
