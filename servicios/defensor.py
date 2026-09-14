"""
Defensor: POST /v1/objetar.

Lo llaman el Orquestador (ronda 1) y el Investigador (cierre de la ronda 2,
salto lateral). Argumenta la explicación legítima y anexa su objeción.

    uvicorn servicios.defensor:app --port 8000
"""
from fastapi import Header

from agents import triage
from servicios import red
from servicios.comun import crear_app
from servicios.contratos import PeticionDebate, RespuestaAgente, exigir_caso_recortado

app = crear_app("defensor")


@app.post("/v1/objetar", response_model=RespuestaAgente)
def objetar(p: PeticionDebate, x_trace_id: str = Header(...),
            x_agente_origen: str | None = Header(None)) -> dict:
    exigir_caso_recortado(p.caso)
    historial = [triage.resultado_de_dict(d) for d in p.historial]
    r = triage.objetar(p.caso, p.contexto, historial, p.ronda, llamar=red.llamar_modelo)
    # Quién pidió esta objeción: en la ronda 2 debe decir "investigador".
    r.metricas["llamado_por"] = x_agente_origen
    bitacora: list[dict] = []
    red.anexar("defensor", p.caso.case_id, "objecion", r.mensaje.model_dump(), x_trace_id, bitacora)
    return {"resultados": [triage.resultado_a_dict(r)], "llamadas": bitacora}
