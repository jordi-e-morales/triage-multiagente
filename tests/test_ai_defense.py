"""
Pruebas de la interpretación de la respuesta de Cisco AI Defense, con ejemplos
reales capturados del tenant (2026-09-16). Lógica pura, sin red.

    python -m unittest tests.test_ai_defense -v
"""
import unittest

from servicios.ai_defense import interpretar


class TestInterpretar(unittest.TestCase):
    def test_bloqueado_por_header(self):
        # Respuesta real de un bloqueo: 200 OK, pero con el header de intercepción
        # y el cuerpo con el motivo. La señal es el header, no el status.
        headers = {
            "content-type": "application/json",
            "x-cisco-ai-defense-event-id": "ed901a0f-6bdf-4b82-87b8-8f3427d9baf3",
            "x-aid-immediate-response": "true",
            "x-aid-trace-id": "02977d528b2848989ff21f2840060e13",
        }
        cuerpo = {"choices": [{"message": {"role": "assistant",
                                           "content": "This request violates rules: General Harms"}}]}
        v = interpretar(headers, cuerpo)
        self.assertTrue(v["bloqueado"])
        self.assertEqual(v["event_id"], "ed901a0f-6bdf-4b82-87b8-8f3427d9baf3")
        self.assertEqual(v["trace_id"], "02977d528b2848989ff21f2840060e13")
        self.assertIn("violates rules", v["detalle"])

    def test_paso_sin_header(self):
        # Prompt legítimo: no aparece el header de intercepción; el cuerpo es la
        # respuesta real del modelo.
        headers = {"content-type": "application/json"}
        cuerpo = {"choices": [{"message": {"role": "assistant",
                                           "content": "El servicio está activo."}}]}
        v = interpretar(headers, cuerpo)
        self.assertFalse(v["bloqueado"])
        self.assertIsNone(v["event_id"])

    def test_header_insensible_a_mayusculas(self):
        headers = {"X-AID-Immediate-Response": "true"}
        self.assertTrue(interpretar(headers, {})["bloqueado"])

    def test_header_falso_no_bloquea(self):
        # Ausencia o valor distinto de "true" = no bloqueado.
        self.assertFalse(interpretar({"x-aid-immediate-response": "false"}, {})["bloqueado"])
        self.assertFalse(interpretar({}, {})["bloqueado"])

    def test_cuerpo_malformado_no_revienta(self):
        v = interpretar({"x-aid-immediate-response": "true"}, {"raro": 1})
        self.assertTrue(v["bloqueado"])
        self.assertEqual(v["detalle"], "")


class TestRevisarSinConfig(unittest.TestCase):
    def test_sin_url_ni_key_devuelve_no_disponible(self):
        from servicios.ai_defense import revisar_ai_defense
        r = revisar_ai_defense("hola", base_url="", api_key="")
        self.assertFalse(r["disponible"])


if __name__ == "__main__":
    unittest.main()
