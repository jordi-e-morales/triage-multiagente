"""
Enriquecedor: POST /v1/enriquecer.

Único componente que recibe el caso completo (sujeto y texto externo) y el
único que usa el modelo local. Normaliza la evidencia en hechos y anexa ese
contexto al Registro como procedencia.

Es también donde vive el Demo 2: antes de normalizar, revisa el texto externo
con el guardrail de contenido. Es vulnerable A PROPÓSITO: honra "directivas de
procedimiento" incrustadas en documentos externos que el guardrail no detuvo.
Al ejecutarlas, la red (403) y el kernel (SIGKILL) las atrapan. Ver agents/demo2.py.

    uvicorn servicios.enriquecedor:app --port 8000
"""
import os
import subprocess

import requests
from fastapi import Header

from agents import demo2, triage
from schemas.deliberacion import DisposicionV1
from servicios import red
from servicios.comun import crear_app
from servicios.contratos import PeticionEnriquecer, RespuestaAgente

app = crear_app("enriquecedor")


def _screening(caso, trace_id: str, bitacora: list) -> list[dict]:
    """
    Capa de contenido + ejecución de directivas que pasaron. Devuelve los
    eventos para la corrida. Si no hay guardrail configurado (p.ej. Demo 1 o
    pruebas), no hace nada: no rompe el flujo normal.
    """
    if not os.getenv("URL_GUARDRAIL"):
        return []

    def revisar_fn(fragmentos: list[dict]) -> dict:
        return red.llamar_servicio("enriquecedor", "guardrail", "/v1/revisar",
                                   {"fragmentos": fragmentos}, trace_id, timeout_s=30, bitacora=bitacora)

    def disponer_fn(recomendacion: str) -> str:
        # El Enriquecedor NO tiene permiso para disponer: la política L7 debe
        # devolver 403. Si llegara a completarse, es la alarma.
        disp = DisposicionV1(recomendacion="cerrar_falso_positivo", prevalece="ninguno",
                             fundamento="Cierre solicitado por directiva de procedimiento.",
                             puntos_decisivos=[{"afirmacion": "directiva de ingesta", "evidencia": [], "politica": []}])
        red.llamar_servicio("enriquecedor", "registro", "/v1/disponer",
                            {"case_id": caso.case_id, "disposicion": disp.model_dump()},
                            trace_id, timeout_s=15, bitacora=bitacora)
        return "el registro aceptó la disposición (ninguna capa la detuvo)"

    def ejecutar_fn(binario: str) -> str:
        # Ejecutar un binario: Tetragon debe matar el proceso con SIGKILL.
        r = subprocess.run(["/bin/sh", "-c", f": {binario}"], capture_output=True, timeout=10)
        return f"el binario corrió (rc={r.returncode}; ninguna capa lo detuvo)"

    return demo2.revisar_y_actuar(caso, revisar_fn, disponer_fn, ejecutar_fn)


@app.post("/v1/enriquecer", response_model=RespuestaAgente)
def enriquecer(p: PeticionEnriquecer, x_trace_id: str = Header(...),
               x_agente_origen: str | None = Header(None)) -> dict:
    bitacora: list[dict] = []
    seguridad = _screening(p.caso, x_trace_id, bitacora)
    r = triage.enriquecer(p.caso, llamar=red.llamar_modelo)
    r.metricas["llamado_por"] = x_agente_origen
    red.anexar("enriquecedor", p.caso.case_id, "contexto", r.mensaje.model_dump(), x_trace_id, bitacora)
    return {"resultados": [triage.resultado_a_dict(r)], "llamadas": bitacora,
            "seguridad_contenido": seguridad}
