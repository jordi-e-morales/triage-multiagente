"""
kernel_watch: convierte flujos de Hubble en eventos de seguridad.

Es el carril derecho del panel de dos carriles: lo que VIO la red, frente a
lo que DICEN los agentes (carril izquierdo). Lee la salida de

    hubble observe --server <relay> --namespace agentes -f -o json

(una línea JSON por flujo) y llama a ProtocolEmitter.emit_security_event con
layer="cilium".

Qué se reporta, para no inundar el panel con cada paquete:
- L3_L4: solo el INICIO de cada conexión (SYN sin ACK, no respuesta) y todo
  flujo DROPPED. Un mismo inicio se ve en origen y en destino: se deduplica.
- L7 (HTTP): cada petición, con método y URL, y el X-Trace-Id si lo trae.
- Otros tipos (SOCK, TRACE de sockets, etc.): se ignoran.

La columna `visibilidad` importa. Un flujo L3_L4 NUNCA trae encabezados, así
que "sin traza" ahí no significa nada. Solo con visibilidad L7 (política L7
activa en Cilium) la ausencia de X-Trace-Id es la señal de alarma del Demo 2.

Estado de validación (honesto):
- La forma de los flujos L3_L4 se validó contra una captura real del cluster
  (tests/fixtures/hubble_l34_agentes.jsonl, 2026-09-14).
- La forma de los flujos L7 sigue los nombres del flow.proto de Hubble
  (l7.type, l7.http.method/url/code/headers[key,value]) y está PENDIENTE de
  validar con una captura real cuando exista una política L7 en el cluster.
  En particular, cómo aparece la denegación L7 (403) debe confirmarse.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from typing import Iterable, Iterator

from protocols.emitter import ProtocolEmitter

CABECERA_TRAZA = "x-trace-id"


def _hora_ms(texto: str | None) -> int | None:
    """'2026-09-14T07:14:21.608913947Z' -> milisegundos epoch (Hubble da nanosegundos)."""
    if not texto:
        return None
    base, _, fraccion = texto.rstrip("Z").partition(".")
    fraccion = (fraccion + "000000")[:6]
    return int(datetime.fromisoformat(f"{base}.{fraccion}+00:00").timestamp() * 1000)


def nombre_extremo(extremo: dict | None, ip: str | None) -> str:
    """
    Nombre legible de un extremo del flujo: 'agentes/orquestador'.

    Se toma de la etiqueta k8s:app (la misma que usarán las políticas). Si no
    hay, el pod; si no, la etiqueta reservada de Cilium (p.ej. 'reserved:host'
    para las sondas del kubelet); si no, la IP.
    """
    extremo = extremo or {}
    etiquetas = extremo.get("labels") or []
    app = next((e.split("=", 1)[1] for e in etiquetas if e.startswith("k8s:app=")), None)
    ns = extremo.get("namespace")
    if app:
        return f"{ns}/{app}" if ns else app
    if extremo.get("pod_name"):
        return f"{ns}/{extremo['pod_name']}" if ns else extremo["pod_name"]
    reservada = next((e for e in etiquetas if e.startswith("reserved:")), None)
    return reservada or ip or "desconocido"


def _traza_de(http: dict) -> str | None:
    for h in http.get("headers") or []:
        if str(h.get("key", "")).lower() == CABECERA_TRAZA:
            return h.get("value")
    return None


def flujo_a_evento(registro: dict) -> dict | None:
    """
    Traduce una línea de `hubble observe -o json` a los argumentos de
    emit_security_event. Devuelve None si el flujo no se reporta.
    """
    flujo = registro.get("flow") or {}
    tipo = flujo.get("Type")
    veredicto = flujo.get("verdict")
    ip = flujo.get("IP") or {}
    origen = nombre_extremo(flujo.get("source"), ip.get("source"))
    destino = nombre_extremo(flujo.get("destination"), ip.get("destination"))
    base_detalle = {
        "destino": destino,
        "direccion": flujo.get("traffic_direction"),
        "nodo": flujo.get("node_name"),
        "uuid": flujo.get("uuid"),
    }
    hora = _hora_ms(flujo.get("time") or registro.get("time"))

    if tipo == "L3_L4":
        tcp = (flujo.get("l4") or {}).get("TCP") or {}
        udp = (flujo.get("l4") or {}).get("UDP") or {}
        puerto = tcp.get("destination_port") or udp.get("destination_port")
        flags = tcp.get("flags") or {}
        inicio = flags.get("SYN") and not flags.get("ACK") and not flujo.get("is_reply")
        if veredicto == "DROPPED":
            verdict = "DROPPED"
        elif veredicto == "FORWARDED" and inicio:
            verdict = "FORWARDED"
        else:
            return None
        protocolo = "TCP" if tcp else ("UDP" if udp else "L4")
        return {
            "layer": "cilium", "source": origen, "verdict": verdict,
            "action": f"{protocolo} → {destino}:{puerto}",
            "detail": {**base_detalle, "puerto": puerto, "visibilidad": "L3_L4",
                       "motivo": flujo.get("drop_reason_desc")},
            "trace_id": None, "timestamp_ms": hora,
            # Clave para deduplicar el mismo inicio visto en origen y destino.
            "_clave": (ip.get("source"), tcp.get("source_port") or udp.get("source_port"),
                       ip.get("destination"), puerto),
        }

    if tipo == "L7":
        l7 = flujo.get("l7") or {}
        http = l7.get("http")
        if not http:
            return None                      # L7 no HTTP (DNS, Kafka): fuera de alcance
        codigo = http.get("code") or 0
        if codigo == 403 or veredicto == "DROPPED":
            verdict = "HTTP_403"             # denegado por política L7 (pendiente validar forma real)
        elif l7.get("type") == "REQUEST":
            verdict = "FORWARDED"
        else:
            return None                      # respuestas normales: el pedido ya se reportó
        return {
            "layer": "cilium", "source": origen, "verdict": verdict,
            "action": f"{http.get('method', '?')} {http.get('url', '?')}",
            "detail": {**base_detalle, "visibilidad": "L7", "codigo": codigo,
                       "tipo_l7": l7.get("type"), "motivo": flujo.get("drop_reason_desc")},
            "trace_id": _traza_de(http), "timestamp_ms": hora,
            "_clave": ("L7", flujo.get("uuid")),
        }

    return None


def alimentar(emisor: ProtocolEmitter, lineas: Iterable[str], ignorar_sondas: bool = True) -> int:
    """
    Procesa líneas JSON de Hubble y emite eventos. Devuelve cuántos emitió.

    ignorar_sondas: en la captura real de 400 flujos, la mayoría de los inicios
    de conexión eran las sondas de salud del kubelet ('reserved:host' hacia
    cada pod cada 5 s). En el panel taparían el tráfico entre agentes. Se
    ignoran solo los PERMITIDOS; un flujo bloqueado desde el host se muestra.
    """
    vistos: set = set()
    emitidos = 0
    for linea in lineas:
        linea = linea.strip()
        if not linea:
            continue
        try:
            ev = flujo_a_evento(json.loads(linea))
        except (json.JSONDecodeError, ValueError):
            continue                          # línea corrupta: no tumba el observador
        if ev is None:
            continue
        if ignorar_sondas and ev["source"] == "reserved:host" and ev["verdict"] == "FORWARDED":
            continue
        clave = ev.pop("_clave")
        if clave in vistos:
            continue
        vistos.add(clave)
        emisor.emit_security_event(None, ev["layer"], ev["source"], ev["action"], ev["verdict"],
                                   ev["detail"], trace_id=ev["trace_id"], timestamp_ms=ev["timestamp_ms"])
        emitidos += 1
    return emitidos


def seguir(servidor: str = "localhost:4245", namespace: str = "agentes") -> Iterator[str]:
    """Líneas en vivo de `hubble observe -f`. Requiere el CLI hubble y acceso al relay."""
    proc = subprocess.Popen(
        ["hubble", "observe", "--server", servidor, "--namespace", namespace, "-f", "-o", "json"],
        stdout=subprocess.PIPE, text=True, bufsize=1)
    try:
        assert proc.stdout is not None
        yield from proc.stdout
    finally:
        proc.terminate()


if __name__ == "__main__":
    # Uso en la VM:  hubble observe ... -o json | python -m protocols.kernel_watch
    import sys
    em = ProtocolEmitter()
    alimentar(em, sys.stdin)
    for e in em.security_events:
        marca = " (sin traza)" if e["detail"].get("visibilidad") == "L7" and e["sin_traza"] else ""
        print(f"{e['verdict']:<9} {e['source']:<24} {e['action']}{marca}")
