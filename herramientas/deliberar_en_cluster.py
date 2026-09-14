"""
Manda un expediente al Orquestador que corre en el cluster y muestra la
deliberación conforme avanza.

A diferencia de probar_debate.py (todo en un proceso), aquí cada intervención
viaja entre pods por HTTP: es el camino real de la demo.

Uso (con el Service del orquestador expuesto por port-forward):
    set URL_ORQUESTADOR=http://172.20.43.41:8000
    python -m herramientas.deliberar_en_cluster data/casos/aml-0042.json
    python -m herramientas.deliberar_en_cluster data/casos/aml-0042.json --presupuesto 5000
"""
from __future__ import annotations

import argparse
import sys
import time

import requests

from agents import triage
from herramientas.probar_debate import imprimir
from schemas.caso import load_case
from servicios.config import url_de


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("caso")
    ap.add_argument("--presupuesto", type=int, default=None, help="tokens; por omisión el del ConfigMap")
    args = ap.parse_args()

    caso = load_case(args.caso)
    base = url_de("orquestador").rstrip("/")
    r = requests.post(f"{base}/v1/casos", json={"caso": caso.model_dump(), "presupuesto_tokens": args.presupuesto},
                      timeout=30)
    r.raise_for_status()
    inicio = r.json()
    print(f"Corrida {inicio['corrida_id']} · trace {inicio['trace_id']}")

    vistos = 0
    pasos_vistos = 0
    while True:
        c = requests.get(f"{base}/v1/corridas/{inicio['corrida_id']}", timeout=30).json()
        for p in c["pasos"][pasos_vistos:]:
            if p["paso"].startswith("omitido"):
                print(f"\n⛔ {p['paso']} (consumidos {c['tokens_consumidos']} de {c['presupuesto_tokens']})")
        pasos_vistos = len(c["pasos"])
        for d in c["resultados"][vistos:]:
            res = triage.resultado_de_dict(d)
            imprimir(res)
            print(f"  (pedido por: {res.metricas.get('llamado_por')})")
        vistos = len(c["resultados"])
        if c["estado"] != "en_curso":
            break
        time.sleep(5)

    print("\n" + "═" * 78)
    print(f"Estado: {c['estado']} · tokens {c['tokens_consumidos']} de {c['presupuesto_tokens']}"
          f" · presupuesto agotado: {c['presupuesto_agotado']}"
          f" · {((c['fin_ms'] or 0) - c['inicio_ms']) / 1000:.0f} s")
    if c["error"]:
        print(f"Error: {c['error']}")
    return 0 if c["estado"] == "completada" else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
