"""
Pruebas del servicio observador sin cluster: se le inyectan las capturas
reales de Hubble (tests/fixtures) en lugar del CLI.

    python -m unittest tests.test_observador -v
"""
import os
import unittest
import unittest.mock

import requests

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class TestObservador(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entorno = unittest.mock.patch.dict(os.environ, {"OBSERVADOR_SIN_HUBBLE": "1"})
        cls.entorno.start()
        from servicios import observador
        from tests._servidor import levantar
        cls.obs = observador
        cls.servidor, cls.base = levantar(observador.app)
        for nombre in ("hubble_l34_agentes.jsonl", "hubble_l7_registro.jsonl"):
            with open(os.path.join(FIXTURES, nombre), encoding="utf-8") as f:
                observador.procesar(f.read().splitlines())

    @classmethod
    def tearDownClass(cls):
        cls.servidor.should_exit = True
        cls.entorno.stop()

    def test_sirve_todos_los_eventos_ordenados(self):
        ev = requests.get(f"{self.base}/v1/eventos").json()["eventos"]
        self.assertEqual(len(ev), 9)                     # 7 L3/L4 + 2 L7
        self.assertEqual([e["timestamp_ms"] for e in ev], sorted(e["timestamp_ms"] for e in ev))

    def test_filtra_por_traza(self):
        ev = requests.get(f"{self.base}/v1/eventos").json()["eventos"]
        traza = next(e["trace_id"] for e in ev if e["trace_id"])
        solo = requests.get(f"{self.base}/v1/eventos", params={"trace_id": traza}).json()["eventos"]
        self.assertEqual(len(solo), 1)
        self.assertEqual(solo[0]["action"], "POST http://registro:8000/v1/anexar")

    def test_filtra_por_ventana(self):
        ev = requests.get(f"{self.base}/v1/eventos").json()["eventos"]
        ultimo = ev[-1]["timestamp_ms"]
        tarde = requests.get(f"{self.base}/v1/eventos", params={"desde_ms": ultimo}).json()["eventos"]
        self.assertTrue(all(e["timestamp_ms"] >= ultimo for e in tarde))
        self.assertLess(len(tarde), len(ev))

    def test_estado(self):
        est = requests.get(f"{self.base}/v1/estado").json()
        self.assertEqual(est["eventos_totales"], 9)
        self.assertFalse(est["conectado"])               # en pruebas no hay CLI de Hubble

    def test_memoria_acotada(self):
        self.assertEqual(self.obs.emisor.security_events.maxlen, self.obs.MAX_EVENTOS)


if __name__ == "__main__":
    unittest.main()
