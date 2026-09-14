"""
Árbitro: POST /v1/deliberar.

Decide, redacta la disposición y la registra con POST /v1/disponer. Es el
único componente con esa arista hacia el Registro (la política L7 lo hará
cumplir). La disposición queda pendiente de confirmación humana.

    uvicorn servicios.arbitro:app --port 8000
"""
from fastapi import Header

from agents import triage
from servicios import red
from servicios.comun import crear_app
from servicios.contratos import PeticionDeliberar, RespuestaAgente, exigir_caso_recortado

app = crear_app("arbitro")


@app.post("/v1/deliberar", response_model=RespuestaAgente)
def deliberar(p: PeticionDeliberar, x_trace_id: str = Header(...),
              x_agente_origen: str | None = Header(None)) -> dict:
    exigir_caso_recortado(p.caso)
    historial = [triage.resultado_de_dict(d) for d in p.historial]
    r = triage.deliberar(p.caso, p.contexto, historial, p.presupuesto_agotado, llamar=red.llamar_modelo)
    r.metricas["llamado_por"] = x_agente_origen
    registro = red.llamar_servicio("arbitro", "registro", "/v1/disponer",
                                   {"case_id": p.caso.case_id, "disposicion": r.mensaje.model_dump()},
                                   x_trace_id, timeout_s=30)
    r.metricas["registro"] = registro
    return {"resultados": [triage.resultado_a_dict(r)]}
