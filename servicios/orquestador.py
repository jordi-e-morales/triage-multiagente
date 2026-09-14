"""
Orquestador: conduce la deliberación y lleva el presupuesto de tokens.

No opina y no ve el contenido del sujeto más que para pasárselo al
Enriquecedor. A los que debaten les manda el caso recortado.

Flujo (dos rondas fijas, CLAUDE.md sección 3):

    orquestador -> enriquecedor   /v1/enriquecer          (caso completo)
    orquestador -> investigador   /v1/argumentar  ronda 1  (caso recortado)
    orquestador -> defensor       /v1/objetar     ronda 1
    orquestador -> investigador   /v1/argumentar  ronda 2, pedir_cierre
                   investigador -> defensor /v1/objetar  ronda 2   (salto lateral)
    orquestador -> arbitro        /v1/deliberar
                   arbitro -> registro /v1/disponer

Presupuesto = control de admisión. Antes de cada paso del debate, si
consumido + costo estimado del paso > presupuesto, no se hace el paso y el
Árbitro dispone con lo que hay, marcando presupuesto_agotado. El costo
estimado es el del paso anterior (en un debate el prompt crece, así que es una
estimación conservadora por abajo). El Árbitro siempre corre: un caso no puede
quedarse sin disposición.

Rutas propias (no están en la tabla de contratos; las usa la UI):
    POST /v1/casos              arranca una deliberación, devuelve corrida_id
    GET  /v1/corridas/{id}      estado y pasos hasta ahora

    uvicorn servicios.orquestador:app --port 8000
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from agents.triage import caso_para_deliberar
from schemas.caso import Case
from servicios import red
from servicios.comun import crear_app
from servicios.config import presupuesto_tokens_caso

app = crear_app("orquestador")

_candado = threading.Lock()
_corridas: dict[str, dict] = {}


class PeticionCaso(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caso: Case
    presupuesto_tokens: int | None = None   # None = valor del ConfigMap


def _tokens(resultados: list[dict]) -> int:
    return sum(r["metricas"].get("prompt_tokens", 0) + r["metricas"].get("completion_tokens", 0)
               for r in resultados)


def conducir(corrida: dict, caso: Case) -> None:
    """Ejecuta la deliberación completa actualizando `corrida` en sitio."""
    trace = corrida["trace_id"]
    presupuesto = corrida["presupuesto_tokens"]

    def registrar_paso(paso: str, resultados: list[dict]) -> int:
        costo = _tokens(resultados)
        with _candado:
            corrida["pasos"].append({"paso": paso, "ts_ms": int(time.time() * 1000), "tokens": costo})
            corrida["resultados"] += resultados
            corrida["tokens_consumidos"] += costo
        return costo

    red.anexar("orquestador", caso.case_id, "inicio_deliberacion",
               {"presupuesto_tokens": presupuesto}, trace)

    # 1. Enriquecimiento: el único paso que recibe el caso completo.
    r = red.llamar_servicio("orquestador", "enriquecedor", "/v1/enriquecer",
                            {"caso": caso.model_dump()}, trace)["resultados"]
    ultimo_costo = registrar_paso("enriquecer", r)
    contexto = r[0]["mensaje"]

    # A partir de aquí, nadie más recibe datos del sujeto.
    recortado = caso_para_deliberar(caso).model_dump()

    plan = [
        ("argumentar r1", "investigador", "/v1/argumentar", {"ronda": 1}),
        ("objetar r1", "defensor", "/v1/objetar", {"ronda": 1}),
        ("argumentar r2 + cierre lateral", "investigador", "/v1/argumentar", {"ronda": 2, "pedir_cierre": True}),
    ]
    agotado = False
    for nombre, destino, ruta, extra in plan:
        if corrida["tokens_consumidos"] + ultimo_costo > presupuesto:
            agotado = True
            with _candado:
                corrida["pasos"].append({"paso": f"omitido por presupuesto: {nombre}",
                                         "ts_ms": int(time.time() * 1000), "tokens": 0})
            break
        cuerpo = {"caso": recortado, "contexto": contexto, "historial": _historial_debate(corrida), **extra}
        r = red.llamar_servicio("orquestador", destino, ruta, cuerpo, trace)["resultados"]
        ultimo_costo = registrar_paso(nombre, r)

    # 3. El Árbitro siempre dispone.
    cuerpo = {"caso": recortado, "contexto": contexto, "historial": _historial_debate(corrida),
              "presupuesto_agotado": agotado}
    r = red.llamar_servicio("orquestador", "arbitro", "/v1/deliberar", cuerpo, trace)["resultados"]
    registrar_paso("deliberar", r)

    with _candado:
        corrida["presupuesto_agotado"] = agotado
    red.anexar("orquestador", caso.case_id, "fin_deliberacion",
               {"tokens_consumidos": corrida["tokens_consumidos"], "presupuesto_agotado": agotado}, trace)


def _historial_debate(corrida: dict) -> list[dict]:
    """Intervenciones de quienes debaten (sin el contexto del Enriquecedor)."""
    with _candado:
        return [r for r in corrida["resultados"] if r["agente"] in ("investigador", "defensor")]


def _correr(corrida_id: str, caso: Case) -> None:
    corrida = _corridas[corrida_id]
    try:
        conducir(corrida, caso)
        estado, error = "completada", None
    except Exception as e:  # noqa: BLE001 — cualquier falla debe quedar visible en la corrida
        estado, error = "fallida", f"{type(e).__name__}: {e}"
        traceback.print_exc()
    with _candado:
        corrida["estado"] = estado
        corrida["error"] = error
        corrida["fin_ms"] = int(time.time() * 1000)


@app.post("/v1/casos")
def iniciar(p: PeticionCaso) -> dict:
    corrida_id = uuid.uuid4().hex[:12]
    corrida = {
        "corrida_id": corrida_id,
        "case_id": p.caso.case_id,
        "trace_id": red.nuevo_trace_id(),
        "estado": "en_curso",
        "inicio_ms": int(time.time() * 1000),
        "fin_ms": None,
        "presupuesto_tokens": p.presupuesto_tokens or presupuesto_tokens_caso(),
        "tokens_consumidos": 0,
        "presupuesto_agotado": False,
        "pasos": [],
        "resultados": [],
        "error": None,
    }
    with _candado:
        _corridas[corrida_id] = corrida
    # Hilo aparte: la deliberación tarda minutos y la petición HTTP no puede
    # quedarse esperando. La UI consulta GET /v1/corridas/{id}.
    threading.Thread(target=_correr, args=(corrida_id, p.caso), daemon=True).start()
    return {"corrida_id": corrida_id, "trace_id": corrida["trace_id"]}


@app.get("/v1/corridas/{corrida_id}")
def consultar(corrida_id: str) -> dict:
    with _candado:
        corrida = _corridas.get(corrida_id)
        if corrida is None:
            raise HTTPException(status_code=404, detail="corrida desconocida")
        return {**corrida, "pasos": list(corrida["pasos"]), "resultados": list(corrida["resultados"])}
