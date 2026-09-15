"""
Pruebas de la Fase 4 (inferencia y costo), toda lógica pura, sin GPU ni red:

- Contador de costo (agents/costos.py): el local sale en 0, el grande al precio
  de frontier; el total suma por agente.
- Clasificación de caché (frío/tibio/caliente) por TTFT.
- Selección de precios y backend desde variables de entorno (servicios/config).
- Ensamblado del stream de vLLM y parseo del TTFT de Prometheus
  (agents/llm_provider), que son las piezas puras del cliente vLLM.
- Despacho de backend en servicios/red (ollama vs vllm) según LLM_BACKEND.

    python -m unittest tests.test_costos -v
"""
import importlib
import os
import unittest

from agents import costos
from agents.costos import (Precio, UmbralesCache, clasificar_lectura,
                           costo_resultado, resumen_costo)


class TestContadorCosto(unittest.TestCase):
    def test_local_no_cuesta(self):
        # El Enriquecedor corre en el modelo local: costo marginal ~0.
        m = {"prompt_tokens": 40_000, "completion_tokens": 1_000}
        self.assertEqual(costo_resultado("enriquecedor", m), 0.0)

    def test_grande_cobra_entrada_y_salida_por_separado(self):
        precios = {"local": Precio(0, 0), "grande": Precio(0.60, 2.40)}
        m = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
        # 1M de prompt * 0.60 + 1M de respuesta * 2.40 = 3.00 USD
        self.assertAlmostEqual(costo_resultado("investigador", m, precios), 3.00)

    def test_agente_desconocido_se_trata_como_grande(self):
        precios = {"local": Precio(0, 0), "grande": Precio(0.60, 2.40)}
        m = {"prompt_tokens": 1_000_000, "completion_tokens": 0}
        self.assertAlmostEqual(costo_resultado("desconocido", m, precios), 0.60)

    def test_resumen_suma_por_agente_y_total(self):
        precios = {"local": Precio(0, 0), "grande": Precio(0.60, 2.40)}
        resultados = [
            {"agente": "enriquecedor", "metricas": {"prompt_tokens": 30_000, "completion_tokens": 500}},
            {"agente": "investigador", "metricas": {"prompt_tokens": 1_000_000, "completion_tokens": 0}},
            {"agente": "arbitro", "metricas": {"prompt_tokens": 0, "completion_tokens": 1_000_000}},
        ]
        r = resumen_costo(resultados, precios)
        self.assertEqual(r["prompt_tokens"], 1_030_000)
        self.assertEqual(r["completion_tokens"], 1_000_500)
        # investigador 0.60 + arbitro 2.40 + enriquecedor 0 = 3.00
        self.assertAlmostEqual(r["total_usd"], 3.00)
        roles = {a["agente"]: a["rol"] for a in r["por_agente"]}
        self.assertEqual(roles, {"enriquecedor": "local", "investigador": "grande", "arbitro": "grande"})

    def test_resumen_tolera_resultados_sin_metricas(self):
        r = resumen_costo([{"agente": "arbitro"}])
        self.assertEqual(r["total_usd"], 0.0)
        self.assertEqual(r["por_agente"][0]["prompt_tokens"], 0)


class TestClasificacionCache(unittest.TestCase):
    def setUp(self):
        self.u = UmbralesCache(caliente_max_ms=300, tibio_max_ms=1500)

    def test_tres_estados(self):
        self.assertEqual(clasificar_lectura(120, self.u), "caliente")
        self.assertEqual(clasificar_lectura(900, self.u), "tibio")
        self.assertEqual(clasificar_lectura(4000, self.u), "frío")

    def test_fronteras_inclusivas_por_abajo(self):
        # El umbral pertenece al estado más rápido (<=).
        self.assertEqual(clasificar_lectura(300, self.u), "caliente")
        self.assertEqual(clasificar_lectura(1500, self.u), "tibio")
        self.assertEqual(clasificar_lectura(1500.1, self.u), "frío")


class TestConfigPreciosBackend(unittest.TestCase):
    """Precios y backend salen de variables de entorno (ConfigMap en el cluster)."""

    def _reload_config(self):
        import servicios.config as cfg
        return importlib.reload(cfg)

    def test_backend_por_defecto_ollama(self):
        os.environ.pop("LLM_BACKEND", None)
        cfg = self._reload_config()
        self.assertEqual(cfg.backend(), "ollama")

    def test_backend_vllm_desde_entorno(self):
        os.environ["LLM_BACKEND"] = "vllm"
        try:
            cfg = self._reload_config()
            self.assertEqual(cfg.backend(), "vllm")
        finally:
            os.environ.pop("LLM_BACKEND", None)
            self._reload_config()

    def test_precios_por_defecto(self):
        for k in ("PRECIO_LOCAL_ENTRADA", "PRECIO_LOCAL_SALIDA",
                  "PRECIO_GRANDE_ENTRADA", "PRECIO_GRANDE_SALIDA"):
            os.environ.pop(k, None)
        cfg = self._reload_config()
        p = cfg.precios()
        self.assertEqual((p["local"].entrada, p["local"].salida), (0.0, 0.0))
        self.assertEqual((p["grande"].entrada, p["grande"].salida), (0.60, 2.40))

    def test_precios_configurables(self):
        os.environ["PRECIO_GRANDE_ENTRADA"] = "1.25"
        try:
            cfg = self._reload_config()
            self.assertEqual(cfg.precios()["grande"].entrada, 1.25)
        finally:
            os.environ.pop("PRECIO_GRANDE_ENTRADA", None)
            self._reload_config()


class TestEnsamblarStreamVLLM(unittest.TestCase):
    def test_junta_contenido_tokens_y_finish(self):
        from agents.llm_provider import _ensamblar_stream
        chunks = [
            {"choices": [{"delta": {"role": "assistant"}}]},          # sin contenido
            {"choices": [{"delta": {"content": "hola "}}]},           # primer contenido -> idx 1
            {"choices": [{"delta": {"content": "mundo"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 42, "completion_tokens": 7}},
        ]
        ens = _ensamblar_stream(chunks)
        self.assertEqual(ens["texto"], "hola mundo")
        self.assertEqual(ens["prompt_tokens"], 42)
        self.assertEqual(ens["completion_tokens"], 7)
        self.assertEqual(ens["finish_reason"], "stop")
        self.assertEqual(ens["indice_primer_contenido"], 1)

    def test_stream_vacio(self):
        from agents.llm_provider import _ensamblar_stream
        ens = _ensamblar_stream([])
        self.assertEqual(ens["texto"], "")
        self.assertIsNone(ens["indice_primer_contenido"])


class TestTTFTPrometheus(unittest.TestCase):
    def test_promedio_en_ms(self):
        from agents.llm_provider import ttft_desde_prometheus
        metrics = (
            "# HELP vllm:time_to_first_token_seconds ...\n"
            "# TYPE vllm:time_to_first_token_seconds histogram\n"
            'vllm:time_to_first_token_seconds_sum{model_name="x"} 1.5\n'
            'vllm:time_to_first_token_seconds_count{model_name="x"} 3\n'
        )
        # 1.5 s / 3 = 0.5 s = 500 ms
        self.assertAlmostEqual(ttft_desde_prometheus(metrics), 500.0)

    def test_ausente_devuelve_none(self):
        from agents.llm_provider import ttft_desde_prometheus
        self.assertIsNone(ttft_desde_prometheus("otra_metrica 1\n"))

    def test_cuenta_cero_devuelve_none(self):
        from agents.llm_provider import ttft_desde_prometheus
        metrics = ("vllm:time_to_first_token_seconds_sum 0.0\n"
                   "vllm:time_to_first_token_seconds_count 0\n")
        self.assertIsNone(ttft_desde_prometheus(metrics))


class TestDespachoBackend(unittest.TestCase):
    """red.LLAMAR debe elegir el cliente correcto según LLM_BACKEND al importar."""

    def _reload_red(self):
        import servicios.config as cfg
        import servicios.red as red
        importlib.reload(cfg)
        return importlib.reload(red)

    def test_ollama_por_defecto(self):
        os.environ.pop("LLM_BACKEND", None)
        red = self._reload_red()
        self.assertEqual(red.LLAMAR.__name__, "call_ollama_estructurado")

    def test_vllm_cuando_se_pide(self):
        os.environ["LLM_BACKEND"] = "vllm"
        try:
            red = self._reload_red()
            self.assertEqual(red.LLAMAR.__name__, "call_vllm_estructurado")
        finally:
            os.environ.pop("LLM_BACKEND", None)
            self._reload_red()


if __name__ == "__main__":
    unittest.main()
