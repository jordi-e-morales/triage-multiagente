"""
Contador de costo y clasificación de caché (Fase 4).

Dos ideas que la sesión quiere hacer visibles:

1. "El costo de una malla vive en las aristas": cada agente que lee el mismo
   expediente lo prefillea; el impuesto de contexto se paga en cada handoff,
   salvo que se comparta la caché. El contador suma tokens y dinero por agente.

2. "Lo local se queda local por costo": el Enriquecedor corre en el modelo
   local (costo marginal ~0), y solo Investigador/Defensor/Árbitro justifican
   el modelo grande ("frontier" con precio real, aunque corra local).

Lógica pura, sin red: se prueba sin GPU. Los precios y umbrales se inyectan
(vienen de servicios/config.py, configurables por variable de entorno).
"""
from __future__ import annotations

from dataclasses import dataclass

# Qué modelo usa cada agente (rol), para asignarle precio.
ROL_POR_AGENTE = {
    "enriquecedor": "local",
    "orquestador": "local",     # el orquestador casi no infiere; si lo hace, local
    "investigador": "grande",
    "defensor": "grande",
    "arbitro": "grande",
}


@dataclass(frozen=True)
class Precio:
    """USD por 1,000,000 de tokens, separando entrada (prompt) y salida."""
    entrada: float
    salida: float


# Precios por omisión. El local es 0: corre en nuestro hardware, costo marginal
# ~cero (es el punto de la sesión). El grande lleva precio real de un frontier
# asignado, aunque en el lab corra local. Configurables en config.py.
PRECIOS_DEFAULT = {
    "local": Precio(entrada=0.0, salida=0.0),
    "grande": Precio(entrada=0.60, salida=2.40),
}


def _precio_de(agente: str, precios: dict[str, Precio]) -> Precio:
    return precios[ROL_POR_AGENTE.get(agente, "grande")]


def costo_resultado(agente: str, metricas: dict, precios: dict[str, Precio] | None = None) -> float:
    """Costo en USD de una intervención, según sus tokens y el precio de su rol."""
    precios = precios or PRECIOS_DEFAULT
    p = _precio_de(agente, precios)
    ent = metricas.get("prompt_tokens", 0) / 1_000_000 * p.entrada
    sal = metricas.get("completion_tokens", 0) / 1_000_000 * p.salida
    return ent + sal


def resumen_costo(resultados: list[dict], precios: dict[str, Precio] | None = None) -> dict:
    """
    Suma tokens y costo por agente y total. `resultados` son los dicts de la
    corrida (cada uno con 'agente' y 'metricas').
    """
    precios = precios or PRECIOS_DEFAULT
    por_agente = []
    total_usd = 0.0
    total_prompt = total_comp = 0
    for r in resultados:
        agente = r.get("agente", "?")
        m = r.get("metricas", {})
        usd = costo_resultado(agente, m, precios)
        total_usd += usd
        total_prompt += m.get("prompt_tokens", 0)
        total_comp += m.get("completion_tokens", 0)
        por_agente.append({
            "agente": agente,
            "rol": ROL_POR_AGENTE.get(agente, "grande"),
            "prompt_tokens": m.get("prompt_tokens", 0),
            "completion_tokens": m.get("completion_tokens", 0),
            "usd": round(usd, 6),
        })
    return {
        "total_usd": round(total_usd, 6),
        "prompt_tokens": total_prompt,
        "completion_tokens": total_comp,
        "por_agente": por_agente,
    }


# ─── Clasificación de caché: las tres barras del Demo 2 (frío/tibio/caliente) ──

@dataclass(frozen=True)
class UmbralesCache:
    """Fronteras de TTFT (ms) entre estados de caché. Se calibran en dCloud."""
    caliente_max_ms: float   # por debajo: el estado seguía en VRAM
    tibio_max_ms: float      # por debajo: se leyó de NVMe; por encima: frío


def clasificar_lectura(ttft_ms: float, umbrales: UmbralesCache) -> str:
    """
    Traduce el TTFT medido a estado de caché:
      caliente  el prefix estaba en VRAM (lo más rápido)
      tibio     se recuperó del offload en NVMe
      frío      hubo que recalcular el prefill completo
    """
    if ttft_ms <= umbrales.caliente_max_ms:
        return "caliente"
    if ttft_ms <= umbrales.tibio_max_ms:
        return "tibio"
    return "frío"
