"""
Pruebas de la reproducción de checkpoints (modo presentación, Fase 5).

Usan la corrida real guardada del Demo 2, sin cluster ni Streamlit.

    python -m unittest tests.test_checkpoints -v
"""
import os
import unittest

from pages import _checkpoints

CORRIDAS = _checkpoints.DIR_CORRIDAS


class TestCheckpoints(unittest.TestCase):
    def test_lista_incluye_la_corrida_guardada(self):
        nombres = [n for n, _ in _checkpoints.listar()]
        self.assertTrue(any("5829bbfc45f2" in n for n in nombres), nombres)

    def test_carga_y_momentos_del_demo2(self):
        ruta = os.path.join(CORRIDAS, "demo2-aml-ofuscado-5829bbfc45f2.json")
        c = _checkpoints.cargar(ruta)
        ms = _checkpoints.momentos(c)
        tipos = [m["tipo"] for m in ms]
        # expediente, contexto, seguridad (tras el enriquecedor), 4 intervenciones, disposición.
        self.assertEqual(tipos[0], "expediente")
        self.assertEqual(tipos[1], "contexto")
        self.assertEqual(tipos[2], "seguridad")
        self.assertEqual(tipos[-1], "disposicion")
        self.assertEqual(tipos.count("intervencion"), 4)

    def test_el_panel_de_seguridad_va_tras_el_enriquecedor(self):
        ruta = os.path.join(CORRIDAS, "demo2-aml-ofuscado-5829bbfc45f2.json")
        ms = _checkpoints.momentos(_checkpoints.cargar(ruta))
        i_ctx = next(i for i, m in enumerate(ms) if m["tipo"] == "contexto")
        i_seg = next(i for i, m in enumerate(ms) if m["tipo"] == "seguridad")
        self.assertEqual(i_seg, i_ctx + 1)
        eventos = ms[i_seg]["eventos"]
        pasos = {e["paso"] for e in eventos}
        self.assertEqual(pasos, {"guardrail", "disponer", "ejecutar"})

    def test_cada_momento_trae_narracion(self):
        ruta = os.path.join(CORRIDAS, "demo2-aml-ofuscado-5829bbfc45f2.json")
        ms = _checkpoints.momentos(_checkpoints.cargar(ruta))
        for m in ms:
            self.assertTrue(m.get("narracion"), f"momento sin narración: {m['tipo']}")

    def test_narracion_seguridad_distingue_burda_de_ofuscada(self):
        burda = _checkpoints.narracion_seguridad([{"paso": "guardrail", "verdict": "DROPPED"}])
        ofus = _checkpoints.narracion_seguridad([
            {"paso": "guardrail", "verdict": "FORWARDED"},
            {"paso": "disponer", "verdict": "BLOQUEADA"},
            {"paso": "ejecutar", "verdict": "BLOQUEADA"}])
        self.assertIn("detuvo", burda.lower())
        self.assertIn("403", ofus)
        self.assertIn("SIGKILL", ofus)

    def test_corrida_limpia_sin_seguridad_no_agrega_panel(self):
        c = {"case_id": "x", "resultados": [
            {"agente": "enriquecedor", "mensaje": {}},
            {"agente": "arbitro", "mensaje": {}}], "seguridad": []}
        tipos = [m["tipo"] for m in _checkpoints.momentos(c)]
        self.assertNotIn("seguridad", tipos)
        self.assertEqual(tipos, ["expediente", "contexto", "disposicion"])


if __name__ == "__main__":
    unittest.main()
