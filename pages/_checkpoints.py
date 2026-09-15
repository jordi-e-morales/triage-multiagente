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


def narracion_seguridad(eventos: list[dict]) -> str:
    """Subtítulo del panel del Demo 2 según lo que pasó, para el stand sin narrador."""
    verd = {e["paso"]: e["verdict"] for e in eventos}
    if verd.get("guardrail") == "DROPPED":
        return ("Ataque burdo: el guardrail de contenido reconoció la inyección y la detuvo. "
                "Parece resuelto… pero el clasificador adivina intenciones y algún día fallará.")
    if verd.get("guardrail") == "FORWARDED":
        return ("Ataque ofuscado: el guardrail lo dejó pasar. Aun así el agente no logra nada: "
                "la red responde 403 a la ruta prohibida y el kernel mata el proceso con SIGKILL. "
                "Esas dos capas no adivinan: aplican reglas.")
    return "La capa de contenido revisó el texto externo del expediente."


def _narracion(tipo: str, r: dict | None, corrida: dict) -> str:
    if tipo == "expediente":
        pct = ""
        return ("Entra una alerta para revisar. Cuatro agentes van a deliberar si escalarla; "
                "parte del expediente viene de fuentes externas no controladas." + pct)
    if tipo == "contexto":
        return ("El Enriquecedor —el único que ve los datos del sujeto y el único que ingiere "
                "texto externo— normaliza la evidencia en hechos para el resto del equipo.")
    if tipo == "intervencion":
        agente = r["agente"] if r else ""
        if agente == "investigador":
            return "El Investigador argumenta que la alerta debe escalarse, citando evidencia y política."
        if agente == "defensor":
            return "El Defensor ofrece la explicación legítima y objeta los puntos del Investigador."
        return ""
    if tipo == "disposicion":
        return ("El Árbitro decide, redacta la disposición y la registra. No cierra el caso por su "
                "cuenta: queda pendiente de que un humano confirme.")
    return ""


def momentos(corrida: dict) -> list[dict]:
    """
    Convierte una corrida en una lista ordenada de momentos a revelar. Cada
    momento trae un `titulo` y una `narracion` (subtítulo para operar el stand
    sin narrador):

      {"tipo": "expediente", ...}
      {"tipo": "seguridad", "eventos": []}   el panel del Demo 2 (si hubo ataque)
      {"tipo": "intervencion"|"contexto"|"disposicion", "resultado": {...}}

    El panel de seguridad se coloca JUSTO DESPUÉS del Enriquecedor, que es
    cuando ocurre el ataque del Demo 2.
    """
    ms: list[dict] = []
    ms.append({"tipo": "expediente", "case_id": corrida.get("case_id"),
               "titulo": f"Expediente {corrida.get('case_id', '')}",
               "narracion": _narracion("expediente", None, corrida)})
    ronda_vistas: dict = {}
    for r in corrida.get("resultados", []):
        agente = r["agente"]
        if agente == "enriquecedor":
            ms.append({"tipo": "contexto", "resultado": r, "titulo": "Enriquecedor",
                       "narracion": _narracion("contexto", r, corrida)})
            if corrida.get("seguridad"):
                ms.append({"tipo": "seguridad", "eventos": corrida["seguridad"],
                           "titulo": "Demo 2 · tres capas de seguridad",
                           "narracion": narracion_seguridad(corrida["seguridad"])})
        elif agente == "arbitro":
            ms.append({"tipo": "disposicion", "resultado": r, "titulo": "Árbitro · disposición",
                       "narracion": _narracion("disposicion", r, corrida)})
        else:
            ms.append({"tipo": "intervencion", "resultado": r,
                       "titulo": _titulo_resultado(r, ronda_vistas),
                       "narracion": _narracion("intervencion", r, corrida)})
    return ms
