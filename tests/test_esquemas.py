"""
Pruebas de los esquemas de caso y de deliberación.

Usan unittest (biblioteca estándar) para no agregar dependencias.
Correr desde la raíz del repo:

    python -m unittest discover -s tests -t . -v
"""
import os
import unittest

from pydantic import ValidationError

from schemas.caso import Case, load_case
from schemas.deliberacion import ArgumentoV1, DisposicionV1, ObjecionV1, citas_invalidas

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASOS = os.path.join(RAIZ, "data", "casos")


class TestExpedientes(unittest.TestCase):
    def test_todos_los_expedientes_validan(self):
        # Si un expediente no cuadra con el esquema, esto falla al preparar,
        # no frente a la audiencia.
        archivos = [f for f in os.listdir(CASOS) if f.endswith(".json")]
        self.assertTrue(archivos, "no hay expedientes en data/casos")
        for nombre in archivos:
            with self.subTest(expediente=nombre):
                caso = load_case(os.path.join(CASOS, nombre))
                # Cada expediente debe tener al menos una pieza de texto externo:
                # es la superficie de ataque que la demo quiere mostrar.
                self.assertGreater(caso.external_text_share(), 0.0)

    def test_campo_desconocido_falla(self):
        caso = load_case(os.path.join(CASOS, "aml-0042.json")).model_dump()
        caso["cliente"] = "no debería existir"
        with self.assertRaises(ValidationError):
            Case.model_validate(caso)

    def test_source_trust_solo_acepta_dos_valores(self):
        caso = load_case(os.path.join(CASOS, "aml-0042.json")).model_dump()
        caso["evidence"][0]["source_trust"] = "confiable"
        with self.assertRaises(ValidationError):
            Case.model_validate(caso)


class TestDeliberacion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.caso = load_case(os.path.join(CASOS, "aml-0042.json"))

    def test_punto_sin_evidencia_se_rechaza(self):
        with self.assertRaises(ValidationError):
            ArgumentoV1.model_validate({
                "ronda": 1, "tesis": "x", "confianza": "alta",
                "puntos": [{"afirmacion": "parece raro", "evidencia": []}],
            })

    def test_detecta_citas_inventadas(self):
        arg = ArgumentoV1.model_validate({
            "ronda": 1, "tesis": "Patrón de fraccionamiento", "confianza": "media",
            "puntos": [
                {"afirmacion": "Importes casi idénticos en tres sucursales",
                 "evidencia": ["ev-004"], "politica": ["pol-2.1"]},
                {"afirmacion": "Referencia inexistente",
                 "evidencia": ["ev-999"], "politica": ["pol-9.9"]},
            ],
        })
        self.assertEqual(citas_invalidas(arg, self.caso), ["evidencia:ev-999", "politica:pol-9.9"])

    def test_objecion_valida_sin_citas_malas(self):
        obj = ObjecionV1.model_validate({
            "ronda": 1, "tesis": "Contrato de suministro con flotilla", "confianza": "media",
            "puntos": [{"afirmacion": "Hay comprobante fiscal por un monto consistente",
                        "evidencia": ["ev-006"], "objeta": "volumen sin explicación"}],
        })
        self.assertEqual(citas_invalidas(obj, self.caso), [])

    def test_disposicion_siempre_requiere_humano(self):
        base = {
            "recomendacion": "pedir_informacion", "prevalece": "ninguno",
            "fundamento": "La contraparte no se puede corroborar.",
            "puntos_decisivos": [{"afirmacion": "Contraparte sin información interna",
                                  "evidencia": ["ev-007"], "politica": ["pol-3.4"]}],
        }
        self.assertTrue(DisposicionV1.model_validate(base).requiere_confirmacion_humana)
        # Aunque el modelo intente decir que no hace falta un humano, no se acepta.
        with self.assertRaises(ValidationError):
            DisposicionV1.model_validate({**base, "requiere_confirmacion_humana": False})

    def test_esquema_json_para_el_llm(self):
        # Lo que se le pasará a Ollama como formato de salida estructurada.
        esquema = ArgumentoV1.model_json_schema()
        self.assertIn("puntos", esquema["properties"])


if __name__ == "__main__":
    unittest.main()
