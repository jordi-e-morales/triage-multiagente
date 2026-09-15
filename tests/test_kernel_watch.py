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

FIXTURE_403 = os.path.join(os.path.dirname(FIXTURE), "hubble_l7_403.jsonl")


def _lineas_403():
    with open(FIXTURE_403, encoding="utf-8") as f:
        return f.read().splitlines()


class TestCapturaReal403(unittest.TestCase):
    """
    Captura real con la política estricta: el Enriquecedor intenta
    POST /v1/disponer (403) y POST /v1/anexar (permitido, 422 por cuerpo vacío).
    Orden: petición DROPPED, respuesta 403, petición anexar, respuesta 422.
    """

    def test_una_denegacion_se_reporta_una_vez(self):
        em = ProtocolEmitter()
        kernel_watch.alimentar(em, _lineas_403())
        denegados = [e for e in em.security_events if e["verdict"] == "HTTP_403"]
        self.assertEqual(len(denegados), 1)
        d = denegados[0]
        self.assertEqual(d["source"], "agentes/enriquecedor")
        self.assertEqual(d["detail"]["destino"], "agentes/registro")
        self.assertEqual(d["action"], "POST http://registro:8000/v1/disponer")
        self.assertEqual(d["trace_id"], "sonda-politica")        # de la petición DROPPED

    def test_la_arista_legitima_sigue_pasando(self):
        em = ProtocolEmitter()
        kernel_watch.alimentar(em, _lineas_403())
        permitidos = [e for e in em.security_events if e["verdict"] == "FORWARDED"]
        self.assertEqual([e["action"] for e in permitidos], ["POST http://registro:8000/v1/anexar"])

    def test_orden_inverso_tambien_una_vez(self):
        lineas = _lineas_403()
        em = ProtocolEmitter()
        kernel_watch.alimentar(em, [lineas[1], lineas[0]])       # respuesta 403 antes que la petición
        self.assertEqual(sum(e["verdict"] == "HTTP_403" for e in em.security_events), 1)


FIXTURE_TETRAGON = os.path.join(os.path.dirname(FIXTURE), "tetragon_sigkill.jsonl")


class TestCapturaRealTetragon(unittest.TestCase):
    """Captura real: dos SIGKILL a exec desde el Enriquecedor y un process_exec normal."""

    def setUp(self):
        with open(FIXTURE_TETRAGON, encoding="utf-8") as f:
            self.lineas = f.read().splitlines()
        self.em = ProtocolEmitter()
        self.n = kernel_watch.alimentar_tetragon(self.em, self.lineas)

    def test_solo_las_acciones_de_enforcement(self):
        self.assertEqual(self.n, 2)
        self.assertEqual({e["verdict"] for e in self.em.security_events}, {"SIGKILL"})
        self.assertEqual({e["layer"] for e in self.em.security_events}, {"tetragon"})

    def test_origen_y_accion(self):
        acciones = sorted(e["action"] for e in self.em.security_events)
        self.assertEqual(acciones, ["exec /usr/bin/dash", "exec /usr/bin/env"])
        for e in self.em.security_events:
            self.assertEqual(e["source"], "agentes/enriquecedor")
            self.assertEqual(e["detail"]["politica"], "agentes-sin-exec")
            self.assertEqual(e["detail"]["visibilidad"], "kernel")
            self.assertTrue(e["sin_traza"])

    def test_deduplica(self):
        em = ProtocolEmitter()
        self.assertEqual(kernel_watch.alimentar_tetragon(em, self.lineas + self.lineas), 2)

    # La rotación (renombrar un archivo abierto) es semántica de Linux, que es
    # donde corre el observador; Windows no permite renombrar un archivo abierto.
    @unittest.skipUnless(os.name == "posix", "rotación de archivos abiertos: solo Linux")
    def test_seguir_archivo_con_rotacion(self):
        import tempfile
        import threading
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "eventos.log")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write("uno\n")
            recibidas: list[str] = []
            gen = kernel_watch.seguir_archivo(ruta, espera_s=0.05)

            def consumir():
                for linea in gen:
                    recibidas.append(linea.strip())
                    if len(recibidas) == 3:
                        return

            hilo = threading.Thread(target=consumir, daemon=True)
            hilo.start()
            import time
            time.sleep(0.2)
            with open(ruta, "a", encoding="utf-8") as f:
                f.write("dos\n")
            time.sleep(0.2)
            # Rotación: se renombra y se crea uno nuevo con el mismo nombre.
            os.replace(ruta, ruta + ".1")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write("tres\n")
            hilo.join(timeout=3)
            self.assertEqual(recibidas, ["uno", "dos", "tres"])


if __name__ == "__main__":
    unittest.main()
