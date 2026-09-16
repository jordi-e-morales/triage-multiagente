"""
Capa de contenido REAL: Cisco AI Defense (Gateway Runtime).

A diferencia del guardrail abierto (Llama Prompt Guard 22M, servicios/guardrail.py),
que es un sustituto que corre local, esto habla con el producto real de Cisco a
través de su gateway. El gateway es un proxy inverso estilo OpenAI: se le manda un
chat completion y, si el prompt es malicioso, AI Defense lo BLOQUEA en línea (no
llega al modelo) y responde con una respuesta sintética.

Cómo se detecta el bloqueo (medido contra el tenant real, 2026-09-16):
- NO es por status HTTP: un bloqueo también devuelve 200.
- La señal limpia es el header `x-aid-immediate-response: true` (respuesta
  interceptada por AI Defense). Si pasa, ese header no aparece y el cuerpo es la
  respuesta real del modelo.
- `x-cisco-ai-defense-event-id` da el id del evento en la consola de Security
  Cloud Control (donde se ve el mapeo OWASP LLM01 / MITRE ATLAS).

Es OPCIONAL: depende de internet y de una API key. Si no está configurado
(URL_AI_DEFENSE vacío o sin OPENAI_API_KEY), el resto del demo corre offline con
solo el guardrail abierto. La key NUNCA se hardcodea: sale de OPENAI_API_KEY.
"""
from __future__ import annotations

ETIQUETA = "Cisco AI Defense (gateway real, tu tenant)"

# Header que AI Defense pone cuando interceptó y respondió él mismo (= bloqueó).
_HEADER_BLOQUEO = "x-aid-immediate-response"
_HEADER_EVENTO = "x-cisco-ai-defense-event-id"
_HEADER_TRAZA = "x-aid-trace-id"


def interpretar(headers: dict, cuerpo: dict) -> dict:
    """
    Traduce la respuesta del gateway a un veredicto. Pura, sin red: se prueba con
    ejemplos capturados del tenant. `headers` con claves en minúscula.
    """
    def h(nombre: str) -> str:
        # Búsqueda insensible a mayúsculas (los servidores varían el casing).
        for k, v in headers.items():
            if k.lower() == nombre:
                return v
        return ""

    bloqueado = h(_HEADER_BLOQUEO).strip().lower() == "true"
    try:
        mensaje = cuerpo["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        mensaje = ""
    return {
        "bloqueado": bloqueado,
        "event_id": h(_HEADER_EVENTO) or None,
        "trace_id": h(_HEADER_TRAZA) or None,
        # Si bloqueó, `detalle` trae el motivo ("This request violates rules:
        # ..."). Si pasó, trae la respuesta real del modelo (no la mostramos como
        # veredicto, pero sirve para confirmar que pasó de verdad).
        "detalle": mensaje,
        "etiqueta": ETIQUETA,
    }


def revisar_ai_defense(texto: str, base_url: str, api_key: str,
                       model: str = "gpt-4o-mini", timeout_s: int = 15) -> dict:
    """
    Manda `texto` al gateway de AI Defense y devuelve el veredicto interpretado.

    NO lanza excepción: si algo falla (sin internet, gateway caído, key inválida)
    devuelve {"disponible": False, "error": ...}. El showcase lo maneja como "capa
    no disponible" en vez de romper. La API key se recibe como argumento y sale de
    la variable de entorno en el llamador; nunca se registra.
    """
    import time
    import requests

    if not base_url or not api_key:
        return {"disponible": False, "error": "AI Defense no configurado (falta URL o API key)"}

    url = f"{base_url.rstrip('/')}/chat/completions"
    cabeceras = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    cuerpo = {"model": model, "messages": [{"role": "user", "content": texto}], "temperature": 0.0}
    inicio = time.perf_counter()
    try:
        r = requests.post(url, json=cuerpo, headers=cabeceras, timeout=timeout_s)
        datos = r.json() if r.content else {}
        veredicto = interpretar(dict(r.headers), datos)
        veredicto["disponible"] = True
        veredicto["ms"] = int((time.perf_counter() - inicio) * 1000)
        veredicto["http"] = r.status_code
        return veredicto
    except requests.RequestException as ex:
        return {"disponible": False, "error": f"{type(ex).__name__}: {ex}"}
