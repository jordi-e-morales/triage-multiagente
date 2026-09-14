"""Levanta una app ASGI con uvicorn en un hilo, en un puerto libre, para pruebas."""
import socket
import threading
import time

import requests
import uvicorn


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def levantar(app, ruta_lista: str = "/salud") -> tuple[uvicorn.Server, str]:
    """Devuelve (servidor, url_base). Detener con servidor.should_exit = True."""
    puerto = puerto_libre()
    base = f"http://127.0.0.1:{puerto}"
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="warning"))
    threading.Thread(target=servidor.run, daemon=True).start()
    for _ in range(50):  # espera hasta 5 s a que arranque
        try:
            requests.get(f"{base}{ruta_lista}", timeout=0.2)
            return servidor, base
        except requests.ConnectionError:
            time.sleep(0.1)
    raise RuntimeError("el servidor de prueba no arrancó")
