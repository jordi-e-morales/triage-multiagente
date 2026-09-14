"""
Piezas comunes a los cinco servicios HTTP.

Cada componente (orquestador, enriquecedor, investigador, defensor, árbitro
y registro) es un proceso separado que en Kubernetes corre en su propio pod.
Eso es lo que hace posibles los controles: si fueran funciones dentro de un
mismo proceso, las llamadas entre ellos serían de memoria y ni Cilium ni
Tetragon tendrían nada que ver.

Todos se configuran con variables de entorno, que es como Kubernetes le pasa
configuración a un contenedor (campo `env` del Deployment).
"""
from __future__ import annotations

import os

from fastapi import FastAPI

# URL del servidor de modelos. No se asume que Ollama corre "aquí mismo":
# en el cluster será otro contenedor con su propio Service (p.ej.
# http://ollama:11434). Cambiar de backend es cambiar esta variable.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")


def crear_app(componente: str) -> FastAPI:
    """
    Crea la aplicación FastAPI de un componente con lo mínimo común.

    `/salud` lo usa Kubernetes para saber si el contenedor está vivo
    (readinessProbe/livenessProbe). No forma parte de los contratos de la
    sección 3 de CLAUDE.md; la política L7 deberá permitirlo aparte.
    """
    app = FastAPI(title=f"{componente}", version="0.1.0")

    @app.get("/salud")
    def salud() -> dict:
        return {"componente": componente, "estado": "ok"}

    return app
