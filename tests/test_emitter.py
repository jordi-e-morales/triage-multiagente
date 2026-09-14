"""
Pruebas de la cuarta lista del ProtocolEmitter (security_events).

    python -m unittest tests.test_emitter -v
"""
import unittest

from protocols.emitter import PipelineContext, ProtocolEmitter


class TestEventosDeSeguridad(unittest.TestCase):
    def setUp(self):
        self.em = ProtocolEmitter()
        self.ctx = PipelineContext(session_id="s1", trace_id="t1", application_id="aml-0042", emitter=self.em)

    def test_lista_separada_de_las_tres_existentes(self):
        self.em.emit_security_event(self.ctx, "cilium", "agentes/enriquecedor", "POST registro/v1/anexar",
                                    "FORWARDED", {}, trace_id="t1")
        self.assertEqual(len(self.em.security_events), 1)
        self.assertEqual((self.em.slim_messages, self.em.otel_spans, self.em.dir_events), ([], [], []))

    def test_flujo_sin_traza_queda_marcado(self):
        ev = self.em.emit_security_event(None, "cilium", "agentes/enriquecedor", "POST registro/v1/disponer",
                                         "HTTP_403", "denegado por política L7")
        self.assertTrue(ev["sin_traza"])
        self.assertIsNone(ev["session_id"])

    def test_rechaza_capa_o_veredicto_desconocidos(self):
        with self.assertRaises(ValueError):
            self.em.emit_security_event(self.ctx, "firewall", "x", "y", "FORWARDED", {})
        with self.assertRaises(ValueError):
            self.em.emit_security_event(self.ctx, "cilium", "x", "y", "ALLOWED", {})

    def test_conserva_la_hora_de_la_capa(self):
        ev = self.em.emit_security_event(self.ctx, "tetragon", "x", "exec", "SIGKILL", {}, timestamp_ms=123)
        self.assertEqual(ev["timestamp_ms"], 123)


if __name__ == "__main__":
    unittest.main()
