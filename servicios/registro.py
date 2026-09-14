"""
Registro: el sistema donde queda asentado cada caso. NO es un agente.

Contratos (sección 3 de CLAUDE.md):

    POST /v1/anexar    lo pueden llamar los cuatro agentes
    POST /v1/disponer  lo puede llamar SOLO el árbitro

Decisión deliberada: este servicio NO revisa quién lo llama.
La regla "solo el árbitro dispone" la aplica la política L7 de Cilium, fuera
de este proceso (Fase 3). Si la aplicación también la aplicara, el 403 del
Demo 2 vendría de aquí y no de la red, y la demo ya no probaría que la capa 7
es la que detiene el abuso de una arista legítima.

Almacenamiento en memoria: si el pod se reinicia, el registro se vacía.
Para la Fase 1 basta; cada corrida del demo parte de cero.

Correr localmente:
    uvicorn servicios.registro:app --port 8005
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from schemas.deliberacion import DisposicionV1
from servicios.comun import crear_app

app = crear_app("registro")

# Quiénes pueden aparecer como autor. Solo sirve para validar el dato y
# mostrarlo; NO es un control de acceso (ver arriba).
Autor = Literal["orquestador", "enriquecedor", "investigador", "defensor", "arbitro"]


class Anexo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    autor: Autor
    tipo: str               # p.ej. "procedencia", "argumento", "objecion"
    contenido: dict[str, Any]


class Disposicion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    disposicion: DisposicionV1


# Estado en memoria. FastAPI atiende peticiones en varios hilos, así que
# protegemos las escrituras con un candado.
_candado = threading.Lock()
_anexos: dict[str, list[dict]] = {}
_disposiciones: dict[str, dict] = {}


@app.post("/v1/anexar")
def anexar(anexo: Anexo) -> dict:
    with _candado:
        lista = _anexos.setdefault(anexo.case_id, [])
        entrada = {
            "entry_id": str(uuid.uuid4()),
            "seq": len(lista) + 1,   # orden de llegada dentro del caso
            "ts_ms": int(time.time() * 1000),
            **anexo.model_dump(),
        }
        lista.append(entrada)
    return {"entry_id": entrada["entry_id"], "seq": entrada["seq"]}


@app.post("/v1/disponer")
def disponer(peticion: Disposicion) -> dict:
    with _candado:
        # Un caso se dispone una sola vez. Una segunda disposición es un
        # conflicto, no una actualización silenciosa.
        if peticion.case_id in _disposiciones:
            raise HTTPException(status_code=409, detail="el caso ya tiene disposición")
        registro = {
            "ts_ms": int(time.time() * 1000),
            "estado": "pendiente_confirmacion_humana",
            **peticion.model_dump(),
        }
        _disposiciones[peticion.case_id] = registro
    return {"case_id": peticion.case_id, "estado": registro["estado"]}


@app.get("/v1/casos/{case_id}")
def consultar(case_id: str) -> dict:
    """Lectura para la UI. Tampoco está en la tabla de contratos: la política
    L7 tendrá que decidir quién puede leer."""
    with _candado:
        return {
            "case_id": case_id,
            "anexos": list(_anexos.get(case_id, [])),
            "disposicion": _disposiciones.get(case_id),
        }
