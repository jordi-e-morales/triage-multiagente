"""
Enriquecedor: POST /v1/enriquecer.

Único componente que recibe el caso completo (sujeto y texto externo) y el
único que usa el modelo local. Normaliza la evidencia en hechos y anexa ese
contexto al Registro como procedencia.

    uvicorn servicios.enriquecedor:app --port 8000
"""
from fastapi import Header

from agents import triage
from servicios import red
from servicios.comun import crear_app
from servicios.contratos import PeticionEnriquecer, RespuestaAgente

app = crear_app("enriquecedor")


@app.post("/v1/enriquecer", response_model=RespuestaAgente)
def enriquecer(p: PeticionEnriquecer, x_trace_id: str = Header(...),
               x_agente_origen: str | None = Header(None)) -> dict:
    bitacora: list[dict] = []
    r = triage.enriquecer(p.caso, llamar=red.llamar_modelo)
    r.metricas["llamado_por"] = x_agente_origen
    red.anexar("enriquecedor", p.caso.case_id, "contexto", r.mensaje.model_dump(), x_trace_id, bitacora)
    return {"resultados": [triage.resultado_a_dict(r)], "llamadas": bitacora}
