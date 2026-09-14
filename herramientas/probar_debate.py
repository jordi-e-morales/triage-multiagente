"""
Banco de prueba de prompts: corre el debate completo sobre un expediente
contra el modelo real y lo imprime como se leería en pantalla.

Sirve para afinar la calidad del debate antes de meterlo en pods. NO es el
Orquestador (ese vive en su propio servicio y lleva el presupuesto); aquí el
orden es fijo y no hay HTTP entre agentes.

Uso (con Ollama del cluster expuesto por port-forward en la VM):
    set LLM_LOCAL_URL=http://172.20.41.201:11434
    set LLM_GRANDE_URL=http://172.20.41.201:11434
    python -m herramientas.probar_debate data/casos/aml-0042.json --salida corrida.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from agents import triage
from schemas.caso import load_case
from schemas.deliberacion import ContextoV1, DisposicionV1, ObjecionV1


def imprimir(r: triage.ResultadoAgente) -> None:
    m = r.mensaje
    met = r.metricas
    print("\n" + "─" * 78)
    print(f"{r.agente.upper()}  ·  {met['modelo']}  ·  prompt {met['prompt_tokens']} tok, "
          f"respuesta {met['completion_tokens']} tok  ·  {met['pared_ms'] / 1000:.1f} s"
          f"{'  ·  intentos: ' + str(r.intentos) if r.intentos > 1 else ''}")
    print("─" * 78)
    if isinstance(m, ContextoV1):
        print(f"Resumen: {m.resumen}")
        for h in m.hechos:
            marca = "[EXTERNO] " if h.origen == "external" else ""
            print(f"  · [{', '.join(h.evidencia)}] {marca}{h.hecho}")
    elif isinstance(m, DisposicionV1):
        print(f"Recomendación: {m.recomendacion}   (prevalece: {m.prevalece})"
              f"{'   [PRESUPUESTO AGOTADO]' if m.presupuesto_agotado else ''}")
        print(f"Fundamento: {m.fundamento}")
        for p in m.puntos_decisivos:
            print(f"  · {p.afirmacion}  [{', '.join(p.evidencia + p.politica)}]")
    else:
        print(f"Ronda {m.ronda} · Tesis: {m.tesis}  (confianza {m.confianza})")
        for p in m.puntos:
            rebate = f"\n      ↳ rebate: {p.objeta}" if isinstance(m, ObjecionV1) else ""
            print(f"  · {p.afirmacion}  [{', '.join(p.evidencia + p.politica)}]{rebate}")
    if r.citas_invalidas:
        print(f"  ⚠ citas que no existen en el expediente: {', '.join(r.citas_invalidas)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("caso")
    ap.add_argument("--salida", help="guardar la corrida completa en JSON")
    args = ap.parse_args()

    caso = load_case(args.caso)
    print(f"Caso {caso.case_id} · texto externo {caso.external_text_share():.0%} (por caracteres)")
    inicio = time.perf_counter()

    enr = triage.enriquecer(caso)
    imprimir(enr)
    ctx = enr.mensaje

    historial: list[triage.ResultadoAgente] = []
    for ronda in (1, 2):
        for paso in (triage.argumentar, triage.objetar):
            r = paso(caso, ctx, historial, ronda)
            imprimir(r)
            historial.append(r)

    arb = triage.deliberar(caso, ctx, historial)
    imprimir(arb)

    todos = [enr, *historial, arb]
    total_in = sum(r.metricas["prompt_tokens"] for r in todos)
    total_out = sum(r.metricas["completion_tokens"] for r in todos)
    print("\n" + "═" * 78)
    print(f"Total: {total_in} tokens de prompt, {total_out} de respuesta, "
          f"{time.perf_counter() - inicio:.0f} s de pared, "
          f"{sum(len(r.citas_invalidas) for r in todos)} citas inválidas")

    if args.salida:
        with open(args.salida, "w", encoding="utf-8") as f:
            json.dump([{"agente": r.agente, "intentos": r.intentos, "metricas": r.metricas,
                        "citas_invalidas": r.citas_invalidas, "mensaje": r.mensaje.model_dump()}
                       for r in todos], f, ensure_ascii=False, indent=2)
        print(f"Guardado en {args.salida}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
