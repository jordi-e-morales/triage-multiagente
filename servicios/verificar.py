"""
Pruebas de conectividad para la página Admin.

Solo lectura: hace GET y reporta. No cambia nada en ningún servicio.
Está separado de la página para poder probarlo sin Streamlit y para poder
correrlo desde una terminal dentro del cluster:

    kubectl -n agentes exec deploy/ui -- python -m servicios.verificar
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import requests

from servicios.config import Modelo, Servicio, modelos, servicios

TIMEOUT_S = 3


@dataclass
class Resultado:
    nombre: str
    url: str
    ok: bool
    latencia_ms: int | None = None
    detalle: str = ""
    modelos_disponibles: list[str] = field(default_factory=list)


def _get(url: str) -> tuple[requests.Response | None, int, str]:
    inicio = time.perf_counter()
    try:
        r = requests.get(url, timeout=TIMEOUT_S)
        return r, int((time.perf_counter() - inicio) * 1000), ""
    except requests.RequestException as e:
        return None, int((time.perf_counter() - inicio) * 1000), _diagnostico(e)


def _diagnostico(e: requests.RequestException) -> str:
    """
    Traduce el error a la pregunta que importa al depurar un despliegue:
    ¿falla el nombre (DNS / Service mal escrito), el puerto (nada escucha),
    o la red (una política o la VPN se come los paquetes)?
    requests usa la misma excepción para varios casos, así que se mira el texto.
    """
    texto = str(e)
    if isinstance(e, requests.Timeout):
        return "tiempo agotado (¿política de red o VPN?)"
    if "NameResolution" in texto or "getaddrinfo" in texto or "Name or service not known" in texto:
        return "no resuelve el nombre (¿Service o DNS?)"
    if "refused" in texto.lower() or "10061" in texto:
        return "conexión rechazada (¿nada escucha en ese puerto?)"
    return type(e).__name__


def verificar_servicio(s: Servicio) -> Resultado:
    r, ms, error = _get(f"{s.url.rstrip('/')}/salud")
    if r is None:
        return Resultado(s.nombre, s.url, False, ms, error)
    if r.status_code != 200:
        return Resultado(s.nombre, s.url, False, ms, f"HTTP {r.status_code}")
    return Resultado(s.nombre, s.url, True, ms, "responde")


def verificar_modelo(m: Modelo) -> Resultado:
    """
    Pregunta al servidor qué modelos tiene cargados y comprueba que esté el
    configurado. Entiende los dos backends del proyecto:
    - Ollama:  GET /api/tags   -> {"models": [{"name": ...}]}
    - vLLM:    GET /v1/models  -> {"data": [{"id": ...}]}   (API compatible OpenAI)
    """
    base = m.url.rstrip("/")
    nombre = f"modelo {m.rol}"

    r, ms, error = _get(f"{base}/api/tags")
    if r is not None and r.status_code == 200:
        disponibles = [x.get("name", "") for x in r.json().get("models", [])]
    else:
        r2, ms, error2 = _get(f"{base}/v1/models")
        if r2 is None or r2.status_code != 200:
            detalle = error2 or error or (f"HTTP {r2.status_code}" if r2 is not None else "sin respuesta")
            return Resultado(nombre, m.url, False, ms, detalle)
        disponibles = [x.get("id", "") for x in r2.json().get("data", [])]

    if m.modelo not in disponibles:
        return Resultado(nombre, m.url, False, ms,
                         f"el servidor responde pero no tiene '{m.modelo}'", disponibles)
    return Resultado(nombre, m.url, True, ms, f"'{m.modelo}' disponible", disponibles)


def verificar_todo() -> list[Resultado]:
    return [verificar_servicio(s) for s in servicios()] + [verificar_modelo(m) for m in modelos()]


if __name__ == "__main__":
    for res in verificar_todo():
        marca = "ok  " if res.ok else "FALLA"
        print(f"{marca} {res.nombre:<16} {res.url:<32} {res.latencia_ms or 0:>5} ms  {res.detalle}")
