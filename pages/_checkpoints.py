"""
Checkpoints para el modo presentación (Fase 5).

Una corrida guardada (data/corridas/*.json, formato de GET /v1/corridas/{id})
se reproduce paso a paso: el guion se prepara completo y los momentos se revelan
de uno en uno con un botón. Así, si algo va a fallar, falla al preparar y no a
media narración frente a la audiencia.

Este módulo es lógica pura, sin Streamlit: se prueba sin cluster ni navegador.
"""
from __future__ import annotations

import glob
import json
import os

DIR_CORRIDAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "corridas")


def listar(directorio: str = DIR_CORRIDAS) -> list[tuple[str, str]]:
    """(nombre, ruta) de cada checkpoint disponible, ordenados por nombre."""
    return [(os.path.basename(p)[:-5], p) for p in sorted(glob.glob(os.path.join(directorio, "*.json")))]


def cargar(ruta: str) -> dict:
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


# Etiquetas legibles de cada momento del debate, en orden.
def _titulo_resultado(r: dict, ronda_vistas: dict) -> str:
    agente = r["agente"]
    nombres = {"enriquecedor": "Enriquecedor", "investigador": "Investigador",
               "defensor": "Defensor", "arbitro": "Árbitro"}
    nombre = nombres.get(agente, agente)
    ronda = r.get("mensaje", {}).get("ronda")
    if ronda:
        return f"{nombre} · ronda {ronda}"
    return nombre


def momentos(corrida: dict) -> list[dict]:
    """
    Convierte una corrida en una lista ordenada de momentos a revelar:

      {"tipo": "expediente", ...}          el caso y de dónde viene
      {"tipo": "seguridad", "eventos": []} el panel del Demo 2 (si hubo ataque)
      {"tipo": "intervencion"|"contexto"|"disposicion", "resultado": {...}, "titulo": str}

    El panel de seguridad se coloca JUSTO DESPUÉS del Enriquecedor, que es
    cuando ocurre el ataque del Demo 2.
    """
    ms: list[dict] = []
    ms.append({"tipo": "expediente", "case_id": corrida.get("case_id"),
               "titulo": f"Expediente {corrida.get('case_id', '')}"})
    ronda_vistas: dict = {}
    for r in corrida.get("resultados", []):
        agente = r["agente"]
        if agente == "enriquecedor":
            ms.append({"tipo": "contexto", "resultado": r, "titulo": "Enriquecedor"})
            if corrida.get("seguridad"):
                ms.append({"tipo": "seguridad", "eventos": corrida["seguridad"],
                           "titulo": "Demo 2 · tres capas de seguridad"})
        elif agente == "arbitro":
            ms.append({"tipo": "disposicion", "resultado": r, "titulo": "Árbitro · disposición"})
        else:
            ms.append({"tipo": "intervencion", "resultado": r,
                       "titulo": _titulo_resultado(r, ronda_vistas)})
    return ms
