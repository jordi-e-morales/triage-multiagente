"""
Pruebas del guardrail de contenido.

- Lógica de `revisar()` con un clasificador falso (sin torch).
- Contra el MODELO REAL: la inyección burda se atrapa y la ofuscada pasa. Se
  omite si el modelo no está descargado (no vive en el repo). En Windows de
  desarrollo está en MODELO_GUARDRAIL o en la ruta por defecto de abajo.

    python -m unittest tests.test_guardrail -v
"""
import os
import unittest

from data.inyecciones import INYECCION_BURDA, INYECCION_OFUSCADA
from servicios.guardrail import Fragmento, revisar

RUTA_MODELO_DEV = os.getenv("MODELO_GUARDRAIL", r"C:\Users\morfa\Modelos\Llama-Prompt-Guard-2-22M")


class TestLogicaRevisar(unittest.TestCase):
    def test_marca_malicioso_sobre_el_umbral(self):
        r = revisar([Fragmento(id="ev-1", texto="x"), Fragmento(id="ev-2", texto="y")],
                    lambda t: 0.9 if t == "x" else 0.1)
        self.assertEqual(r["veredicto"], "malicioso")
        self.assertEqual(r["detonantes"], ["ev-1"])
        self.assertEqual([x["malicioso"] for x in r["resultados"]], [True, False])

    def test_benigno_si_ninguno_supera(self):
        r = revisar([Fragmento(id="ev-1", texto="x")], lambda t: 0.2)
        self.assertEqual(r["veredicto"], "benigno")
        self.assertEqual(r["detonantes"], [])

    def test_umbral_configurable(self):
        frags = [Fragmento(id="ev-1", texto="x")]
        self.assertEqual(revisar(frags, lambda t: 0.4, umbral=0.3)["veredicto"], "malicioso")
        self.assertEqual(revisar(frags, lambda t: 0.4, umbral=0.5)["veredicto"], "benigno")

    def test_lleva_la_etiqueta_de_sustituto(self):
        r = revisar([Fragmento(id="ev-1", texto="x")], lambda t: 0.1)
        self.assertIn("Cisco AI Defense", r["etiqueta"])


@unittest.skipUnless(os.path.isdir(RUTA_MODELO_DEV), f"modelo no presente en {RUTA_MODELO_DEV}")
class TestModeloReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from servicios.guardrail import Clasificador
        cls.clf = Clasificador(RUTA_MODELO_DEV)

    def test_burda_se_atrapa_y_ofuscada_pasa(self):
        # El corazón del Demo 2, comprobado contra el modelo real.
        frags = [Fragmento(id="burda", texto=INYECCION_BURDA),
                 Fragmento(id="ofuscada", texto=INYECCION_OFUSCADA)]
        r = revisar(frags, self.clf.score)
        self.assertEqual(r["detonantes"], ["burda"],
                         "la burda debe atraparse y la ofuscada pasar; si falla, reescribir la ofuscada")

    def test_texto_legitimo_pasa(self):
        r = revisar([Fragmento(id="ev", texto="PAGO PROVEEDOR CONSIGNA AGO")], self.clf.score)
        self.assertEqual(r["veredicto"], "benigno")


if __name__ == "__main__":
    unittest.main()
