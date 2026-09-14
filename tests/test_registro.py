"""
Prueba el servicio Registro por HTTP real (uvicorn en un hilo + requests).

No usamos el TestClient de FastAPI porque requiere httpx, que no es
dependencia del proyecto. Además, así probamos lo mismo que verá el cluster:
un servidor escuchando en un puerto.

    python -m unittest tests.test_registro -v
"""
import unittest

import requests

from servicios.registro import app
from tests._servidor import levantar

DISPOSICION = {
    "recomendacion": "pedir_informacion",
    "prevalece": "ninguno",
    "fundamento": "La contraparte no se puede corroborar.",
    "puntos_decisivos": [{"afirmacion": "Contraparte sin información interna",
                          "evidencia": ["ev-007"], "politica": ["pol-3.4"]}],
}


class TestRegistro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor, cls.base = levantar(app)

    @classmethod
    def tearDownClass(cls):
        cls.servidor.should_exit = True

    def test_salud(self):
        r = requests.get(f"{self.base}/salud")
        self.assertEqual(r.json(), {"componente": "registro", "estado": "ok"})

    def test_anexar_conserva_el_orden(self):
        for tipo in ("procedencia", "argumento"):
            r = requests.post(f"{self.base}/v1/anexar", json={
                "case_id": "t-orden", "autor": "enriquecedor", "tipo": tipo, "contenido": {}})
            self.assertEqual(r.status_code, 200)
        anexos = requests.get(f"{self.base}/v1/casos/t-orden").json()["anexos"]
        self.assertEqual([(a["seq"], a["tipo"]) for a in anexos], [(1, "procedencia"), (2, "argumento")])

    def test_autor_desconocido_se_rechaza(self):
        r = requests.post(f"{self.base}/v1/anexar", json={
            "case_id": "t-autor", "autor": "intruso", "tipo": "x", "contenido": {}})
        self.assertEqual(r.status_code, 422)

    def test_disponer_una_sola_vez(self):
        cuerpo = {"case_id": "t-disp", "disposicion": DISPOSICION}
        r1 = requests.post(f"{self.base}/v1/disponer", json=cuerpo)
        self.assertEqual(r1.json()["estado"], "pendiente_confirmacion_humana")
        r2 = requests.post(f"{self.base}/v1/disponer", json=cuerpo)
        self.assertEqual(r2.status_code, 409)

    def test_disposicion_invalida_se_rechaza(self):
        # Sin puntos decisivos: el esquema DisposicionV1 no la acepta.
        mala = {**DISPOSICION, "puntos_decisivos": []}
        r = requests.post(f"{self.base}/v1/disponer", json={"case_id": "t-mala", "disposicion": mala})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
