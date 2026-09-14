"""
Observador: el carril derecho en el cluster.

Sigue en vivo `hubble observe` contra el relay de Hubble, traduce cada flujo
con protocols/kernel_watch y guarda los eventos de seguridad en memoria. La UI
los pide por HTTP para alinearlos con las llamadas de una corrida.

NO es agente: no ve casos, no llama al modelo, no escribe en el Registro. Solo
lee lo que Cilium ya observó. Su única salida de red es hacia hubble-relay.

    GET /v1/eventos?desde_ms=&hasta_ms=&trace_id=   eventos filtrados
    GET /v1/estado                                  conectado, totales, último error

Configuración (variables de entorno):
    HUBBLE_BIN     ruta del CLI (el Deployment lo copia de la imagen de Cilium)
    HUBBLE_SERVER  relay, p.ej. hubble-relay.kube-system.svc.cluster.local:80
    HUBBLE_NAMESPACE  namespace a observar (agentes)

    uvicorn servicios.observador:app --port 8000
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Callable, Iterable

from protocols import kernel_watch
from protocols.emitter import ProtocolEmitter
from servicios.comun import crear_app

MAX_EVENTOS = 5_000   # los más recientes; suficiente para varias deliberaciones

app = crear_app("observador")

_candado = threading.Lock()
_estado = {"conectado": False, "inicio_ms": int(time.time() * 1000), "reconexiones": 0,
           "eventos_totales": 0, "ultimo_error": None, "ultimo_evento_ms": None}


class _EmisorAcotado(ProtocolEmitter):
    """ProtocolEmitter cuya lista de eventos no crece sin límite."""

    def __init__(self):
        super().__init__()
        self.security_events = deque(maxlen=MAX_EVENTOS)  # type: ignore[assignment]

    def emit_security_event(self, *args, **kwargs):
        with _candado:
            ev = super().emit_security_event(*args, **kwargs)
            _estado["eventos_totales"] += 1
            _estado["ultimo_evento_ms"] = ev["timestamp_ms"]
        return ev


emisor = _EmisorAcotado()


def procesar(lineas: Iterable[str]) -> int:
    """Alimenta el emisor con líneas JSON de Hubble. Separado para probarlo sin cluster."""
    return kernel_watch.alimentar(emisor, lineas)


def _bucle(fuente: Callable[[], Iterable[str]]) -> None:
    """Sigue la fuente para siempre; si el CLI termina o falla, reconecta."""
    espera = 1
    while True:
        try:
            with _candado:
                _estado["conectado"] = True
            procesar(fuente())
            error = "hubble observe terminó"
        except Exception as e:  # noqa: BLE001 — cualquier falla se reporta y se reintenta
            error = f"{type(e).__name__}: {e}"
        with _candado:
            _estado.update(conectado=False, ultimo_error=error)
            _estado["reconexiones"] += 1
        time.sleep(espera)
        espera = min(espera * 2, 30)


def _fuente_hubble() -> Iterable[str]:
    return kernel_watch.seguir(
        servidor=os.getenv("HUBBLE_SERVER", "hubble-relay.kube-system.svc.cluster.local:80"),
        namespace=os.getenv("HUBBLE_NAMESPACE", "agentes"),
        binario=os.getenv("HUBBLE_BIN", "hubble"),
    )


@app.on_event("startup")
def _arrancar() -> None:
    # OBSERVADOR_SIN_HUBBLE=1 en pruebas: no lanza el CLI.
    if os.getenv("OBSERVADOR_SIN_HUBBLE") != "1":
        threading.Thread(target=_bucle, args=(_fuente_hubble,), daemon=True).start()


@app.get("/v1/eventos")
def eventos(desde_ms: int | None = None, hasta_ms: int | None = None, trace_id: str | None = None) -> dict:
    with _candado:
        lista = list(emisor.security_events)
    if desde_ms is not None:
        lista = [e for e in lista if e["timestamp_ms"] >= desde_ms]
    if hasta_ms is not None:
        lista = [e for e in lista if e["timestamp_ms"] <= hasta_ms]
    if trace_id is not None:
        lista = [e for e in lista if e["trace_id"] == trace_id]
    return {"eventos": sorted(lista, key=lambda e: e["timestamp_ms"])}


@app.get("/v1/estado")
def estado() -> dict:
    with _candado:
        return {**_estado, "eventos_en_memoria": len(emisor.security_events)}
