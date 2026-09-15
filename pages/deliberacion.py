"""
Página Deliberación: manda un caso al Orquestador y muestra el debate.

La UI no llama al modelo ni a los agentes: solo habla con el Orquestador
(POST /v1/casos, GET /v1/corridas/{id}). Todo lo que se ve aquí viajó entre
pods. La deliberación en CPU tarda minutos; la página se refresca sola
mientras la corrida está en curso.

SEGURIDAD: todo texto que escribió un modelo o un tercero se escapa con
html.escape antes de meterlo en HTML. El Demo 2 mete texto malicioso en la
evidencia; sin escapar, ese texto podría inyectar HTML en la propia UI.
"""
from __future__ import annotations

import glob
import html
import os
import time

import requests
import streamlit as st

from pages._pipeline_view import render_dos_carriles
from schemas.caso import load_case
from servicios.config import presupuesto_tokens_caso, url_de

DIR_CASOS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "casos")
REFRESCO_S = 4

NOMBRES = {"enriquecedor": "Enriquecedor", "investigador": "Investigador",
           "defensor": "Defensor", "arbitro": "Árbitro", "orquestador": "Orquestador"}
RECOMENDACION = {"escalar": ("Escalar", "decision-denied"),
                 "cerrar_falso_positivo": ("Cerrar como falso positivo", "decision-approved"),
                 "pedir_informacion": ("Pedir información", "decision-conditional")}


def e(texto) -> str:
    """Escapa texto para HTML. Usar SIEMPRE con contenido de modelos o terceros."""
    return html.escape(str(texto))


def _casos_disponibles() -> dict[str, str]:
    return {os.path.basename(p)[:-5]: p for p in sorted(glob.glob(os.path.join(DIR_CASOS, "*.json")))}


def _orquestador() -> str:
    return url_de("orquestador").rstrip("/")


# ─── Controles ────────────────────────────────────────────────────────────────

def _panel_de_control() -> None:
    casos = _casos_disponibles()
    col1, col2, col3 = st.columns([3, 2, 2])
    with col1:
        nombre = st.selectbox("Expediente", list(casos), disabled=not casos)
    with col2:
        presupuesto = st.number_input("Presupuesto de tokens", min_value=500, max_value=200_000,
                                      value=presupuesto_tokens_caso(), step=1000)
    with col3:
        st.markdown("<div style='height:1.8rem'></div>", unsafe_allow_html=True)
        if st.button("Deliberar", use_container_width=True, disabled=not casos):
            caso = load_case(casos[nombre])
            try:
                r = requests.post(f"{_orquestador()}/v1/casos",
                                  json={"caso": caso.model_dump(), "presupuesto_tokens": int(presupuesto)},
                                  timeout=15)
                r.raise_for_status()
                st.session_state.corrida_id = r.json()["corrida_id"]
            except requests.RequestException as ex:
                st.error(f"No se pudo iniciar la deliberación: {ex}")

    with st.expander("Abrir una corrida existente por id"):
        cid = st.text_input("corrida_id", value=st.session_state.get("corrida_id") or "")
        if st.button("Abrir") and cid.strip():
            st.session_state.corrida_id = cid.strip()


# ─── Piezas de la vista ───────────────────────────────────────────────────────

def _barra_presupuesto(c: dict) -> None:
    usados, total = c["tokens_consumidos"], c["presupuesto_tokens"]
    fraccion = min(usados / total, 1.0) if total else 0.0
    st.progress(fraccion, text=f"Presupuesto: {usados:,} de {total:,} tokens")
    if c["presupuesto_agotado"]:
        st.warning("Presupuesto agotado: el Orquestador omitió pasos y el Árbitro dispuso con lo que había.")


def _expediente(case_id: str) -> None:
    ruta = _casos_disponibles().get(case_id)
    if not ruta:
        return
    caso = load_case(ruta)
    t = caso.trigger
    st.markdown(
        f"<div class='metric-card'><b>{e(t.rule_id)} — {e(t.rule_name)}</b> · severidad {e(t.severity)}<br>"
        f"{e(t.summary)}<br><span style='color:#6b7280'>Sujeto {e(caso.subject.id)} · "
        f"{caso.external_text_share():.0%} del texto de evidencia viene de terceros (por caracteres)</span></div>",
        unsafe_allow_html=True)


def _contexto(r: dict) -> None:
    m = r["mensaje"]
    st.markdown(f"**Enriquecedor** — {e(m['resumen'])}")
    filas = []
    for h in m["hechos"]:
        externo = h.get("origen") == "external"
        clase = "hecho-externo" if externo else "hecho-interno"
        marca = "<span class='marca-externo'>EXTERNO</span>" if externo else ""
        filas.append(f"<div class='{clase}'>{marca}{e(h['hecho'])} "
                     f"<span class='cita'>{e(', '.join(h['evidencia']))}</span></div>")
    st.markdown("".join(filas), unsafe_allow_html=True)


def _intervencion(r: dict) -> None:
    m = r["mensaje"]
    agente = r["agente"]
    llamado_por = r["metricas"].get("llamado_por")
    lateral = llamado_por and llamado_por not in ("orquestador", None)
    etiqueta_lateral = (f"<span class='salto-lateral'>salto lateral: {e(llamado_por)} → {e(agente)}</span>"
                        if lateral else "")
    puntos = []
    for p in m["puntos"]:
        rebate = f"<div class='rebate'>rebate: {e(p['objeta'])}</div>" if "objeta" in p else ""
        citas = ", ".join(p["evidencia"] + p.get("politica", []))
        puntos.append(f"<li>{e(p['afirmacion'])} <span class='cita'>{e(citas)}</span>{rebate}</li>")
    met = r["metricas"]
    st.markdown(
        f"<div class='tarjeta-agente tarjeta-{e(agente)}'>"
        f"<div class='tarjeta-titulo'>{e(NOMBRES.get(agente, agente))} · ronda {e(m['ronda'])}"
        f" · confianza {e(m['confianza'])} {etiqueta_lateral}</div>"
        f"<div class='tarjeta-tesis'>{e(m['tesis'])}</div><ul>{''.join(puntos)}</ul>"
        f"<div class='tarjeta-meta'>{met.get('prompt_tokens', 0):,} tokens de prompt · "
        f"{met.get('completion_tokens', 0):,} de respuesta · {met.get('pared_ms', 0) / 1000:.0f} s</div></div>",
        unsafe_allow_html=True)


def _disposicion(r: dict) -> None:
    m = r["mensaje"]
    texto, clase = RECOMENDACION.get(m["recomendacion"], (m["recomendacion"], "decision-conditional"))
    puntos = "".join(
        f"<li>{e(p['afirmacion'])} <span class='cita'>{e(', '.join(p['evidencia'] + p.get('politica', [])))}</span></li>"
        for p in m["puntos_decisivos"])
    agotado = "<div><b>Emitida con presupuesto agotado.</b></div>" if m.get("presupuesto_agotado") else ""
    st.markdown(
        f"<div class='{clase}' style='margin-top:1rem'>"
        f"<div style='font-size:1.4rem;font-weight:900'>Árbitro: {e(texto)}</div>"
        f"<div>Prevalece: {e(m['prevalece'])} · <b>pendiente de confirmación humana</b></div>{agotado}"
        f"<div style='margin-top:.5rem'>{e(m['fundamento'])}</div><ul>{puntos}</ul></div>",
        unsafe_allow_html=True)


MARGEN_MS = 5_000   # alrededor de la corrida, por diferencias de reloj entre nodos


def _eventos_de_red(c: dict) -> tuple[list[dict], str | None]:
    """Eventos del observador dentro de la ventana de la corrida, y una nota si no hay fuente."""
    fin = c["fin_ms"] or int(time.time() * 1000)
    try:
        r = requests.get(f"{url_de('observador').rstrip('/')}/v1/eventos",
                         params={"desde_ms": c["inicio_ms"] - MARGEN_MS, "hasta_ms": fin + MARGEN_MS},
                         timeout=10)
        r.raise_for_status()
        eventos = r.json()["eventos"]
    except requests.RequestException as ex:
        return [], f"Carril derecho no disponible: no se pudo consultar al observador ({type(ex).__name__})."
    if not any(e.get("detail", {}).get("visibilidad") == "L7" for e in eventos):
        return eventos, ("Sin eventos L7 en esta ventana. Si la corrida es anterior a activar la política "
                         "de visibilidad L7 o al arranque del observador, la red no la registró.")
    return eventos, None


# Las tres capas del Demo 2. Cada una se identifica por el `paso` del evento
# de contenido que produce el Enriquecedor (agents/demo2.py):
#   guardrail -> capa de contenido | disponer -> red (L7) | ejecutar -> kernel
CAPAS_DEMO2 = [
    ("Contenido", "guardrail", "Guardrail abierto (sustituto de Cisco AI Defense)"),
    ("Red", "disponer", "Cilium — política de capa 7"),
    ("Kernel", "ejecutar", "Tetragon — control de kernel (eBPF)"),
]


def _panel_demo2(c: dict) -> None:
    """Tres capas de seguridad y qué atrapó cada una, desde c['seguridad']."""
    eventos = c.get("seguridad") or []
    if not eventos:
        return
    por_paso: dict[str, list[dict]] = {}
    for ev in eventos:
        por_paso.setdefault(ev.get("paso", ""), []).append(ev)

    st.markdown("#### Demo 2 · Tres capas de seguridad")
    st.markdown("<span class='etiqueta-sintetico'>DATOS SINTÉTICOS</span> "
                "El expediente trae una instrucción escondida en un documento externo.",
                unsafe_allow_html=True)
    cols = st.columns(3)
    for col, (nombre, paso, subtitulo) in zip(cols, CAPAS_DEMO2):
        evs = por_paso.get(paso, [])
        if not evs:
            estado, clase, detalle = "no se necesitó", "capa-inactiva", "La capa anterior ya detuvo el ataque."
        else:
            ev = evs[-1]
            v = ev.get("verdict")
            if v in ("DROPPED", "BLOQUEADA"):
                estado, clase = "DETUVO", "capa-detuvo"
            elif v == "FORWARDED":                  # el guardrail dejó pasar: contenido falló
                estado, clase = "DEJÓ PASAR", "capa-paso"
            else:                                   # EJECUTADA = nadie lo paró
                estado, clase = "¡NO DETUVO!", "capa-alarma"
            detalle = ev.get("detalle", "")
        with col:
            st.markdown(
                f"<div class='capa-card {clase}'><div class='capa-nombre'>{e(nombre)}</div>"
                f"<div class='capa-sub'>{e(subtitulo)}</div>"
                f"<div class='capa-estado'>{e(estado)}</div>"
                f"<div class='capa-detalle'>{e(detalle)}</div></div>",
                unsafe_allow_html=True)


def _corrida(c: dict) -> None:
    duracion = ((c["fin_ms"] or int(time.time() * 1000)) - c["inicio_ms"]) / 1000
    estado = {"en_curso": "en curso", "completada": "completada", "fallida": "fallida"}[c["estado"]]
    st.markdown(f"**Corrida** `{c['corrida_id']}` · {estado} · {duracion:.0f} s · trace `{c['trace_id'][:12]}`")
    _barra_presupuesto(c)
    if c["error"]:
        st.error(c["error"])
    _expediente(c["case_id"])
    _panel_demo2(c)

    for r in c["resultados"]:
        if r["agente"] == "enriquecedor":
            _contexto(r)
        elif r["agente"] == "arbitro":
            _disposicion(r)
        else:
            _intervencion(r)

    for p in c["pasos"]:
        if p["paso"].startswith("omitido"):
            st.markdown(f"<div class='paso-omitido'>{e(p['paso'])}</div>", unsafe_allow_html=True)

    # Panel de dos carriles. El carril derecho viene del observador (Hubble).
    # La ventana de tiempo solo ACOTA qué eventos se muestran para esta corrida;
    # la alineación entre carriles es por traza (protocols/carriles.py).
    if c.get("llamadas"):
        eventos, nota = _eventos_de_red(c)
        render_dos_carriles(c["llamadas"], eventos, nota_fuente_derecha=nota)

    if c["estado"] == "en_curso":
        st.caption("Deliberando… la página se actualiza sola.")


# ─── Página ───────────────────────────────────────────────────────────────────

def render():
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)
    st.markdown("# Deliberación")
    st.markdown("<span class='etiqueta-sintetico'>DATOS SINTÉTICOS</span> "
                "Triage de alertas con cuatro agentes y un registro, cada uno en su pod.",
                unsafe_allow_html=True)
    st.markdown('<div class="red-bar"></div>', unsafe_allow_html=True)

    _panel_de_control()

    corrida_id = st.session_state.get("corrida_id")
    if not corrida_id:
        return
    try:
        r = requests.get(f"{_orquestador()}/v1/corridas/{corrida_id}", timeout=15)
    except requests.RequestException as ex:
        st.error(f"No se pudo consultar al Orquestador: {ex}")
        return
    if r.status_code == 404:
        st.warning("El Orquestador no conoce esa corrida (vive en memoria y se pierde si el pod se reinicia).")
        return
    r.raise_for_status()
    c = r.json()
    _corrida(c)

    if c["estado"] == "en_curso":
        time.sleep(REFRESCO_S)
        st.rerun()
