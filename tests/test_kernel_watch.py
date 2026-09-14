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


FIXTURE_L7 = os.path.join(os.path.dirname(FIXTURE), "hubble_l7_registro.jsonl")


def _lineas_l7():
    with open(FIXTURE_L7, encoding="utf-8") as f:
        return f.read().splitlines()


class TestCapturaRealL7(unittest.TestCase):
    """
    Captura real con la política de visibilidad L7 (herramientas/prueba_l7.py):
    POST /v1/anexar con traza, el mismo sin traza, sus dos respuestas 200,
    un GET /salud desde el orquestador y una sonda desde el host.
    """

    def setUp(self):
        self.em = ProtocolEmitter()
        self.n = kernel_watch.alimentar(self.em, _lineas_l7())

    def test_solo_las_dos_peticiones_de_trabajo(self):
        # Respuestas 200, /salud y la sonda del host no se reportan.
        self.assertEqual(self.n, 2)
        self.assertEqual({e["action"] for e in self.em.security_events},
                         {"POST http://registro:8000/v1/anexar"})

    def test_traza_leida_del_encabezado_real(self):
        trazas = sorted((e["trace_id"] or "") for e in self.em.security_events)
        self.assertEqual(trazas[0], "")                       # la escritura que nadie pidió
        self.assertTrue(trazas[1].startswith("pruebal7"))     # la legítima

    def test_extremos_y_visibilidad(self):
        for e in self.em.security_events:
            self.assertEqual(e["source"], "agentes/orquestador")
            self.assertEqual(e["detail"]["destino"], "agentes/registro")
            self.assertEqual(e["detail"]["visibilidad"], "L7")
            self.assertEqual(e["verdict"], "FORWARDED")
            self.assertTrue(e["detail"]["request_id"])        # lo agrega Envoy

    def test_sin_filtro_se_ven_salud_y_sonda(self):
        em = ProtocolEmitter()
        self.assertEqual(kernel_watch.alimentar(em, _lineas_l7(), ignorar_sondas=False), 4)

    def test_respuesta_denegada_hereda_traza_y_extremos(self):
        # Forma de la DENEGACIÓN construida a partir de la respuesta real (code
        # 403 en vez de 200). PENDIENTE: validar con captura real en la Fase 3.
        peticion, _, respuesta = _lineas_l7()[0], None, json.loads(_lineas_l7()[2])
        respuesta["flow"]["l7"]["http"]["code"] = 403
        respuesta["flow"]["uuid"] = "respuesta-403"
        request_id = kernel_watch._cabecera(json.loads(peticion)["flow"]["l7"]["http"], "x-request-id")
        for h in respuesta["flow"]["l7"]["http"]["headers"]:
            if h["key"].lower() == "x-request-id":
                h["value"] = request_id
        em = ProtocolEmitter()
        kernel_watch.alimentar(em, [peticion, json.dumps(respuesta)])
        denegado = [e for e in em.security_events if e["verdict"] == "HTTP_403"][0]
        self.assertEqual(denegado["source"], "agentes/orquestador")      # invertido: quien pidió
        self.assertEqual(denegado["detail"]["destino"], "agentes/registro")
        self.assertTrue(denegado["trace_id"].startswith("pruebal7"))    # por X-Request-Id


if __name__ == "__main__":
    unittest.main()
