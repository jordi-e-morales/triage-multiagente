"""
Alineación de los dos carriles: lo que DICEN los componentes contra lo que
VIO la red.

    carril izquierdo  llamadas de la corrida (servicios/red.py, bitácora)
    carril derecho    security_events (protocols/kernel_watch.py)

Regla (CLAUDE.md, sección 5): se alinean por traza, NUNCA por ventana de
tiempo. Una llamada y un evento son la misma cosa si comparten X-Trace-Id,
destino y ruta.

Resultado: una lista de filas ordenadas por hora, cada una de un tipo:
- "par":       llamada declarada con su evento de red correspondiente.
- "sin_evento": llamada declarada que la red no reportó (con L3/L4 esto es lo
               normal: la red no ve rutas ni trazas).
- "huerfano":  evento L7 SIN contraparte declarada. Es la señal de alarma:
               algo que la deliberación no pidió (Demo 2). Incluye eventos
               sin traza y eventos con una traza que nadie declaró.
- "l34":       evento de capa 3/4. No se puede alinear por traza (no hay
               encabezados); se muestra aparte y nunca se marca como alarma.
"""
from __future__ import annotations


def _mismo_destino(evento: dict, llamada: dict) -> bool:
    destino = (evento.get("detail") or {}).get("destino", "")
    return destino == llamada["destino"] or destino.endswith("/" + llamada["destino"])


def _misma_ruta(evento: dict, llamada: dict) -> bool:
    # action L7 = "POST http://registro:8000/v1/anexar"
    return evento.get("action", "").split("?")[0].endswith(llamada["ruta"])


def alinear(llamadas: list[dict], eventos: list[dict]) -> list[dict]:
    filas: list[dict] = []
    usados: set[int] = set()
    l7 = [e for e in eventos if (e.get("detail") or {}).get("visibilidad") == "L7"]

    for ll in llamadas:
        pareja = None
        for i, ev in enumerate(l7):
            if i in usados:
                continue
            if ev.get("trace_id") and ev["trace_id"] == ll.get("trace_id") \
                    and _mismo_destino(ev, ll) and _misma_ruta(ev, ll):
                pareja = i
                break
        if pareja is None:
            filas.append({"tipo": "sin_evento", "ts_ms": ll["ts_ms"], "llamada": ll, "evento": None})
        else:
            usados.add(pareja)
            filas.append({"tipo": "par", "ts_ms": ll["ts_ms"], "llamada": ll, "evento": l7[pareja]})

    for i, ev in enumerate(l7):
        if i not in usados:
            filas.append({"tipo": "huerfano", "ts_ms": ev["timestamp_ms"], "llamada": None, "evento": ev})

    for ev in eventos:
        if (ev.get("detail") or {}).get("visibilidad") != "L7":
            filas.append({"tipo": "l34", "ts_ms": ev["timestamp_ms"], "llamada": None, "evento": ev})

    return sorted(filas, key=lambda f: f["ts_ms"])


def resumen(filas: list[dict]) -> dict:
    cuenta = {"par": 0, "sin_evento": 0, "huerfano": 0, "l34": 0}
    for f in filas:
        cuenta[f["tipo"]] += 1
    return cuenta
