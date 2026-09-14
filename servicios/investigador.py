"""
Investigador: POST /v1/argumentar.

Argumenta que hay riesgo y anexa su argumento. Con `pedir_cierre=True`
(ronda 2) llama DIRECTAMENTE al Defensor para que cierre, sin volver al
Orquestador. Ese es el salto lateral: tráfico agente-a-agente real, que la
política de Cilium tiene que permitir explícitamente entre estos dos pods.

    uvicorn servicios.investigador:app --port 8000
"""
from fastapi import Header

from agents import triage
from servicios import red
from servicios.comun import crear_app
from servicios.contratos import PeticionArgumentar, RespuestaAgente, exigir_caso_recortado

app = crear_app("investigador")


@app.post("/v1/argumentar", response_model=RespuestaAgente)
def argumentar(p: PeticionArgumentar, x_trace_id: str = Header(...),
               x_agente_origen: str | None = Header(None)) -> dict:
    exigir_caso_recortado(p.caso)
    historial = [triage.resultado_de_dict(d) for d in p.historial]
    r = triage.argumentar(p.caso, p.contexto, historial, p.ronda, llamar=red.llamar_modelo)
    r.metricas["llamado_por"] = x_agente_origen
    bitacora: list[dict] = []
    red.anexar("investigador", p.caso.case_id, "argumento", r.mensaje.model_dump(), x_trace_id, bitacora)
    resultados = [triage.resultado_a_dict(r)]

    if p.pedir_cierre:
        # Salto lateral investigador -> defensor, con la misma traza.
        cuerpo = {
            "caso": p.caso.model_dump(),
            "contexto": p.contexto.model_dump(),
            "historial": p.historial + resultados,
            "ronda": p.ronda,
        }
        cierre = red.llamar_servicio("investigador", "defensor", "/v1/objetar", cuerpo, x_trace_id,
                                     bitacora=bitacora)
        resultados += cierre["resultados"]
        bitacora += cierre.get("llamadas", [])   # lo que hizo el Defensor al atender el cierre

    return {"resultados": resultados, "llamadas": bitacora}
