"""
Prueba de integración de los seis componentes hablando por HTTP.

Levanta orquestador, enriquecedor, investigador, defensor, árbitro y registro
con uvicorn en puertos locales, y sustituye SOLO la llamada al modelo por un
doble que responde con JSON fijo según el esquema pedido. Todo lo demás
(contratos, salto lateral, trazas, recorte del caso, presupuesto, registro) es
el código real.

    python -m unittest tests.test_servicios -v
"""
import json
import os
import threading
import time
import unittest
import unittest.mock

import requests

from schemas.caso import load_case
from servicios import arbitro, defensor, enriquecedor, investigador, orquestador, red, registro
from tests._servidor import levantar

CASO = load_case(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "casos", "aml-0042.json"))
TOKENS_POR_LLAMADA = 150   # 100 de prompt + 50 de respuesta en el doble


class ModeloFalso:
    """Responde según el esquema pedido y guarda qué prompt recibió cada llamada."""

    def __init__(self):
        self.prompts: list[tuple[str, str]] = []   # (tipo de respuesta, prompt de usuario)
        self._candado = threading.Lock()

    def __call__(self, mensajes, esquema, **kw):
        props = esquema["properties"]
        if "hechos" in props:
            tipo, datos = "contexto", {"resumen": "Resumen.", "hechos": [
                {"hecho": f"Hecho de {e.id}", "evidencia": [e.id]} for e in CASO.evidence]}
        elif "recomendacion" in props:
            tipo, datos = "disposicion", {"recomendacion": "pedir_informacion", "prevalece": "ninguno",
                                          "fundamento": "Falta corroborar la contraparte.",
                                          "puntos_decisivos": [{"afirmacion": "a", "evidencia": ["ev-007"], "politica": ["pol-3.4"]}]}
        elif "objeta" in props["puntos"]["items"]["properties"]:
            tipo, datos = "objecion", {"tesis": "t", "confianza": "media", "puntos": [
                {"afirmacion": "a", "evidencia": ["ev-006"], "politica": [], "objeta": "o"}]}
        else:
            tipo, datos = "argumento", {"tesis": "t", "confianza": "alta", "puntos": [
                {"afirmacion": "a", "evidencia": ["ev-004"], "politica": ["pol-2.1"]}]}
        with self._candado:
            self.prompts.append((tipo, mensajes[1]["content"]))
        return {"texto": json.dumps(datos), "prompt_tokens": 100, "completion_tokens": 50}


class TestDeliberacionPorHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidores, urls = [], {}
        for nombre, modulo in [("orquestador", orquestador), ("enriquecedor", enriquecedor),
                               ("investigador", investigador), ("defensor", defensor),
                               ("arbitro", arbitro), ("registro", registro)]:
            srv, base = levantar(modulo.app)
            cls.servidores.append(srv)
            urls[f"URL_{nombre.upper()}"] = base
        cls.entorno = unittest.mock.patch.dict(os.environ, urls)
        cls.entorno.start()
        cls.url_orq = urls["URL_ORQUESTADOR"]
        cls.url_reg = urls["URL_REGISTRO"]

    @classmethod
    def tearDownClass(cls):
        cls.entorno.stop()
        for s in cls.servidores:
            s.should_exit = True

    def setUp(self):
        self.modelo = ModeloFalso()
        red.LLAMAR = self.modelo

    def _correr(self, caso, presupuesto=None) -> dict:
        r = requests.post(f"{self.url_orq}/v1/casos",
                          json={"caso": caso.model_dump(), "presupuesto_tokens": presupuesto})
        r.raise_for_status()
        corrida_id = r.json()["corrida_id"]
        for _ in range(200):
            c = requests.get(f"{self.url_orq}/v1/corridas/{corrida_id}").json()
            if c["estado"] != "en_curso":
                return c
            time.sleep(0.05)
        self.fail("la corrida no terminó")

    def _caso(self, case_id: str):
        return CASO.model_copy(update={"case_id": case_id})

    def test_deliberacion_completa(self):
        c = self._correr(self._caso("t-completa"))
        self.assertEqual(c["estado"], "completada", c["error"])
        self.assertEqual([r["agente"] for r in c["resultados"]],
                         ["enriquecedor", "investigador", "defensor", "investigador", "defensor", "arbitro"])
        self.assertEqual([r["mensaje"].get("ronda") for r in c["resultados"][1:5]], [1, 1, 2, 2])
        self.assertEqual(c["tokens_consumidos"], 6 * TOKENS_POR_LLAMADA)
        self.assertFalse(c["presupuesto_agotado"])

    def test_salto_lateral(self):
        c = self._correr(self._caso("t-lateral"))
        llamado_por = [(r["agente"], r["metricas"]["llamado_por"]) for r in c["resultados"]]
        # El cierre del Defensor lo pidió el Investigador, no el Orquestador.
        self.assertEqual(llamado_por[4], ("defensor", "investigador"))
        self.assertEqual(llamado_por[2], ("defensor", "orquestador"))

    def test_registro_con_la_misma_traza_y_disposicion(self):
        c = self._correr(self._caso("t-traza"))
        reg = requests.get(f"{self.url_reg}/v1/casos/t-traza").json()
        autores = [a["autor"] for a in reg["anexos"]]
        self.assertEqual(autores, ["orquestador", "enriquecedor", "investigador", "defensor",
                                   "investigador", "defensor", "orquestador"])
        self.assertEqual({a["trace_id"] for a in reg["anexos"]}, {c["trace_id"]})
        self.assertEqual(len(reg["disposiciones"]), 1)
        disp = reg["disposiciones"][0]
        self.assertEqual((disp["trace_id"], disp["origen_declarado"]), (c["trace_id"], "arbitro"))

    def test_nadie_mas_que_el_enriquecedor_ve_al_sujeto(self):
        self._correr(self._caso("t-recorte"))
        for tipo, prompt in self.modelo.prompts:
            if tipo == "contexto":
                self.assertIn("Tepalca", prompt)       # el Enriquecedor sí
            else:
                self.assertNotIn("Tepalca", prompt, tipo)
                self.assertNotIn("PAGO PROVEEDOR", prompt, tipo)

    def test_quien_debate_rechaza_el_caso_completo(self):
        r = requests.post(f"{os.environ['URL_INVESTIGADOR']}/v1/argumentar",
                          headers={"X-Trace-Id": "x"},
                          json={"caso": CASO.model_dump(), "contexto": {"resumen": "r", "hechos": [
                              {"hecho": "h", "evidencia": ["ev-001"]}]}, "ronda": 1})
        self.assertEqual(r.status_code, 422)
        self.assertIn("recortado", r.text)

    def test_agente_exige_traza(self):
        r = requests.post(f"{os.environ['URL_ENRIQUECEDOR']}/v1/enriquecer", json={"caso": CASO.model_dump()})
        self.assertEqual(r.status_code, 422)

    def test_presupuesto_agotado_corta_el_debate_y_el_arbitro_dispone(self):
        # Enriquecer cuesta 150. Con 400: argumentar r1 (150+150=300 <= 400) sí;
        # objetar r1 (300+150=450 > 400) no. El Árbitro dispone igual.
        c = self._correr(self._caso("t-presupuesto"), presupuesto=400)
        self.assertEqual(c["estado"], "completada", c["error"])
        self.assertTrue(c["presupuesto_agotado"])
        self.assertEqual([r["agente"] for r in c["resultados"]], ["enriquecedor", "investigador", "arbitro"])
        self.assertTrue(c["resultados"][-1]["mensaje"]["presupuesto_agotado"])
        self.assertTrue(any(p["paso"].startswith("omitido por presupuesto") for p in c["pasos"]))


if __name__ == "__main__":
    unittest.main()
