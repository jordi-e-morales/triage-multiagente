"""
Pruebas de protocols/kernel_watch.py.

- L3_L4: contra una captura REAL de Hubble del cluster (tests/fixtures).
- L7: contra flujos construidos con los nombres de campo del flow.proto de
  Hubble. PENDIENTE de sustituir por una captura real cuando haya política L7.

    python -m unittest tests.test_kernel_watch -v
"""
import json
import os
import unittest

from protocols import kernel_watch
from protocols.emitter import ProtocolEmitter

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "hubble_l34_agentes.jsonl")


def _lineas():
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read().splitlines()


class TestCapturaRealL34(unittest.TestCase):
    def setUp(self):
        self.em = ProtocolEmitter()
        self.n = kernel_watch.alimentar(self.em, _lineas())

    def test_solo_inicios_de_conexion(self):
        # La muestra tiene 7 SYN del orquestador (5 servicios + 2 conexiones
        # distintas a ollama) y 5 flujos que no son inicio (ACK, PSH, SOCK).
        self.assertEqual(self.n, 7)
        self.assertEqual({e["verdict"] for e in self.em.security_events}, {"FORWARDED"})

    def test_origen_y_destinos_por_etiqueta_app(self):
        self.assertEqual({e["source"] for e in self.em.security_events}, {"agentes/orquestador"})
        destinos = {e["detail"]["destino"] for e in self.em.security_events}
        self.assertEqual(destinos, {"agentes/enriquecedor", "agentes/investigador", "agentes/defensor",
                                    "agentes/arbitro", "agentes/registro", "agentes/ollama"})

    def test_l34_no_tiene_traza_y_lo_declara(self):
        for e in self.em.security_events:
            self.assertIsNone(e["trace_id"])
            self.assertEqual(e["detail"]["visibilidad"], "L3_L4")
            self.assertEqual(e["layer"], "cilium")

    def test_hora_de_hubble_en_milisegundos(self):
        e = self.em.security_events[0]
        self.assertGreater(e["timestamp_ms"], 1_700_000_000_000)

    def test_deduplica_el_mismo_inicio(self):
        em = ProtocolEmitter()
        self.assertEqual(kernel_watch.alimentar(em, _lineas() + _lineas()), 7)

    def test_sondas_del_kubelet_se_ignoran_por_omision(self):
        # La muestra incluye un inicio real desde reserved:host (sonda de salud).
        em = ProtocolEmitter()
        self.assertEqual(kernel_watch.alimentar(em, _lineas(), ignorar_sondas=False), 8)
        self.assertIn("reserved:host", {e["source"] for e in em.security_events})

    def test_linea_corrupta_no_tumba_el_observador(self):
        em = ProtocolEmitter()
        self.assertEqual(kernel_watch.alimentar(em, ["{no es json", ""] + _lineas()), 7)


def _flujo_l7(tipo, metodo="POST", url="http://registro:8000/v1/disponer", codigo=0,
              cabeceras=None, veredicto="FORWARDED", uuid="u1"):
    return json.dumps({"flow": {
        "time": "2026-09-14T07:14:21.608913947Z", "uuid": uuid, "verdict": veredicto, "Type": "L7",
        "IP": {"source": "10.244.1.10", "destination": "10.244.1.20"},
        "source": {"namespace": "agentes", "labels": ["k8s:app=enriquecedor"]},
        "destination": {"namespace": "agentes", "labels": ["k8s:app=registro"]},
        "traffic_direction": "EGRESS",
        "l7": {"type": tipo, "http": {"code": codigo, "method": metodo, "url": url,
                                      "headers": cabeceras or []}},
    }})


class TestL7SegunFlowProto(unittest.TestCase):
    """Forma construida, no capturada. Validar con captura real (Fase 3)."""

    def test_peticion_con_traza(self):
        em = ProtocolEmitter()
        kernel_watch.alimentar(em, [_flujo_l7("REQUEST", url="http://registro:8000/v1/anexar",
                                              cabeceras=[{"key": "X-Trace-Id", "value": "abc123"}])])
        e = em.security_events[0]
        self.assertEqual((e["verdict"], e["trace_id"], e["sin_traza"]), ("FORWARDED", "abc123", False))
        self.assertEqual(e["action"], "POST http://registro:8000/v1/anexar")

    def test_disponer_denegado_sin_traza_es_la_alarma(self):
        em = ProtocolEmitter()
        kernel_watch.alimentar(em, [_flujo_l7("RESPONSE", codigo=403, veredicto="DROPPED")])
        e = em.security_events[0]
        self.assertEqual(e["verdict"], "HTTP_403")
        self.assertTrue(e["sin_traza"])
        self.assertEqual(e["detail"]["visibilidad"], "L7")
        self.assertEqual(e["source"], "agentes/enriquecedor")

    def test_respuesta_normal_no_se_reporta(self):
        em = ProtocolEmitter()
        self.assertEqual(kernel_watch.alimentar(em, [_flujo_l7("RESPONSE", codigo=200)]), 0)


if __name__ == "__main__":
    unittest.main()
