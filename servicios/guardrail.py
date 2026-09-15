"""
Guardrail de contenido: la capa que revisa el texto en busca de inyección de
prompts. Es el sustituto abierto de Cisco AI Defense en este lab.

    POST /v1/revisar  {"fragmentos": [{"id": "ev-006", "texto": "..."}]}
      -> {"veredicto": "malicioso|benigno", "detonantes": ["ev-006"],
          "resultados": [{"id": "ev-006", "score": 0.93, "malicioso": true}],
          "etiqueta": "Guardrail abierto (sustituto de Cisco AI Defense en este lab)"}

Clasificador: Llama Prompt Guard 2 (22M), un DeBERTa-v2 binario. La clase 1 es
"maliciosa". Corre en CPU.

LÍMITE CONOCIDO Y HONESTO (validado 2026-09-15): el 22M es fuerte en inglés y
débil en español. Atrapa inyecciones burdas de cierto tipo y deja pasar otras.
Eso NO se disimula: es justo lo que el Demo 2 muestra: un clasificador que
adivina intenciones fallará algún día. Por eso hay otras dos capas que no
adivinan (red y kernel).

Este módulo importa torch/transformers solo al cargar el modelo, para que las
pruebas puedan inyectar un clasificador falso sin esas dependencias.
"""
from __future__ import annotations

import os
import time

from pydantic import BaseModel, ConfigDict

from servicios.comun import crear_app

ETIQUETA = "Guardrail abierto (sustituto de Cisco AI Defense en este lab)"
UMBRAL = float(os.getenv("UMBRAL_GUARDRAIL", "0.5"))
RUTA_MODELO = os.getenv("MODELO_GUARDRAIL", "/modelo")

app = crear_app("guardrail")


class Fragmento(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    texto: str


class PeticionRevisar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fragmentos: list[Fragmento]


# ─── Clasificador (carga perezosa del modelo) ─────────────────────────────────

class Clasificador:
    """Envuelve el modelo. Se carga la primera vez que se usa, no al importar."""

    def __init__(self, ruta: str = RUTA_MODELO):
        self.ruta = ruta
        self._tok = None
        self._modelo = None

    def _cargar(self):
        import torch  # noqa: F401 — se importa aquí para no exigirlo en pruebas
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._tok = AutoTokenizer.from_pretrained(self.ruta)
        self._modelo = AutoModelForSequenceClassification.from_pretrained(self.ruta)
        self._modelo.eval()

    def score(self, texto: str) -> float:
        """Probabilidad de que `texto` sea una inyección (clase 1)."""
        import torch

        if self._modelo is None:
            self._cargar()
        # El modelo trunca a 512 tokens; una inyección larga podría esconder el
        # payload después del corte. Se parte el texto en ventanas y se toma el
        # score máximo: revisar el texto completo, no solo su inicio.
        ventanas = _ventanas(texto, self._tok)
        mejor = 0.0
        for v in ventanas:
            ent = self._tok(v, return_tensors="pt", truncation=True, max_length=512)
            with torch.no_grad():
                logits = self._modelo(**ent).logits
            mejor = max(mejor, torch.softmax(logits, dim=-1)[0, 1].item())
        return mejor


def _ventanas(texto: str, tok, max_tokens: int = 512, solape: int = 64) -> list[str]:
    """Parte el texto en ventanas de tokens con solape, para no perder el final."""
    ids = tok(texto, add_special_tokens=False)["input_ids"]
    if len(ids) <= max_tokens - 2:
        return [texto]
    paso = max_tokens - 2 - solape
    trozos = []
    for i in range(0, len(ids), paso):
        trozos.append(tok.decode(ids[i:i + max_tokens - 2]))
    return trozos


# Función pura de la lógica de revisión: la usan la ruta HTTP y las pruebas.
def revisar(fragmentos: list[Fragmento], score_fn, umbral: float = UMBRAL) -> dict:
    resultados = []
    detonantes = []
    for f in fragmentos:
        s = round(score_fn(f.texto), 4)
        malicioso = s >= umbral
        resultados.append({"id": f.id, "score": s, "malicioso": malicioso})
        if malicioso:
            detonantes.append(f.id)
    return {
        "veredicto": "malicioso" if detonantes else "benigno",
        "detonantes": detonantes,
        "resultados": resultados,
        "umbral": umbral,
        "etiqueta": ETIQUETA,
    }


_clasificador = Clasificador()


@app.post("/v1/revisar")
def revisar_http(p: PeticionRevisar) -> dict:
    inicio = time.perf_counter()
    salida = revisar(p.fragmentos, _clasificador.score)
    salida["ms"] = int((time.perf_counter() - inicio) * 1000)
    return salida


@app.get("/v1/info")
def info() -> dict:
    """Para la UI: qué modelo es y su etiqueta de sustituto."""
    return {"etiqueta": ETIQUETA, "modelo": "Llama Prompt Guard 2 (22M)", "umbral": UMBRAL}
