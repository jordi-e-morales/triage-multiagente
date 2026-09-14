"""
Llamadas HTTP entre componentes.

Toda llamada de un pod a otro pasa por `llamar_servicio`. Así hay un solo
lugar donde:

- se propaga `X-Trace-Id`: el mismo en toda la deliberación de un caso. Con
  política L7, Hubble ve este header y la UI puede alinear lo que dicen los
  agentes con lo que vio la red (CLAUDE.md, sección 5). Un flujo SIN este
  header es algo que el pipeline no pidió.
- se genera un `X-Span-Id` nuevo por llamada.
- se declara `X-Agente-Origen`. OJO: es solo visibilidad, cualquiera puede
  escribirlo. La identidad verificable es la del pod (Cilium), no este header.

La función que llama al modelo también vive aquí (`LLAMAR`) para que las
pruebas puedan sustituirla en todos los servicios a la vez.
"""
from __future__ import annotations

import os
import time
import uuid

import requests

from agents.llm_provider import call_ollama_estructurado
from servicios.config import url_de

# Sustituible en pruebas: servicios.red.LLAMAR = doble
LLAMAR = call_ollama_estructurado

# En CPU un paso puede tardar varios minutos (el salto lateral encadena dos
# llamadas al modelo). En GPU bastará mucho menos.
TIMEOUT_S = int(os.getenv("TIMEOUT_AGENTE_S", "1800"))


def llamar_modelo(*args, **kwargs):
    """Indirección para que el valor de LLAMAR se lea al momento de llamar."""
    return LLAMAR(*args, **kwargs)


def nuevo_trace_id() -> str:
    return uuid.uuid4().hex


def llamar_servicio(origen: str, destino: str, ruta: str, cuerpo: dict, trace_id: str | None,
                    timeout_s: int | None = None, bitacora: list | None = None) -> dict:
    """
    POST a otro componente propagando la traza. Lanza excepción si no es 2xx.

    bitacora: si se pasa una lista, se le agrega un registro de esta llamada.
    Es el CARRIL IZQUIERDO del panel de dos carriles: lo que el componente
    declara que hizo (origen, destino, ruta, traza, span, cuándo, resultado).
    Se contrasta con lo que vio la red (kernel_watch, carril derecho).
    """
    span_id = uuid.uuid4().hex[:16]
    cabeceras = {"X-Span-Id": span_id, "X-Agente-Origen": origen}
    if trace_id:
        cabeceras["X-Trace-Id"] = trace_id
    inicio_ms = int(time.time() * 1000)
    estado = None
    try:
        r = requests.post(f"{url_de(destino).rstrip('/')}{ruta}", json=cuerpo, headers=cabeceras,
                          timeout=timeout_s or TIMEOUT_S)
        estado = r.status_code
        r.raise_for_status()
        return r.json()
    finally:
        if bitacora is not None:
            bitacora.append({
                "ts_ms": inicio_ms,
                "duracion_ms": int(time.time() * 1000) - inicio_ms,
                "origen": origen, "destino": destino, "ruta": ruta, "metodo": "POST",
                "trace_id": trace_id, "span_id": span_id,
                "estado_http": estado,          # None = no hubo respuesta (timeout, conexión)
            })


def anexar(autor: str, case_id: str, tipo: str, contenido: dict, trace_id: str | None,
           bitacora: list | None = None) -> dict:
    """Anexa al Registro (POST /v1/anexar). Todos los agentes pueden."""
    return llamar_servicio(autor, "registro", "/v1/anexar",
                           {"case_id": case_id, "autor": autor, "tipo": tipo, "contenido": contenido},
                           trace_id, timeout_s=30, bitacora=bitacora)
