"""
Pruebas de los controles que aplica el CÓDIGO alrededor de los agentes.

No prueban la calidad del debate (eso se revisa leyendo la salida real con
herramientas/probar_debate.py). Prueban lo que no puede depender de que el
modelo obedezca: redacción del sujeto, procedencia, campos del código,
reintento y detección de contexto insuficiente.

    python -m unittest tests.test_triage -v
"""
import json
import os
import unittest
import unittest.mock

from fastapi import FastAPI

from agents import triage
from agents.llm_provider import ContextoInsuficiente, call_ollama_estructurado
from schemas.caso import load_case
from schemas.deliberacion import ArgumentoV1, ContextoV1, DisposicionV1, esquema_para_llm
from tests._servidor import levantar

CASO = load_case(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "casos", "aml-0042.json"))


def doble(*respuestas: dict):
    """Función `llamar` falsa: devuelve las respuestas en orden y guarda las llamadas."""
    cola = list(respuestas)
    llamadas = []

    def llamar(mensajes, esquema, **kw):
        llamadas.append({"mensajes": mensajes, "esquema": esquema, **kw})
        return {"texto": json.dumps(cola.pop(0)), "prompt_tokens": 100, "completion_tokens": 50}

    llamar.llamadas = llamadas
    return llamar


def con_cobertura(ctx: dict) -> dict:
    """Agrega un hecho de relleno para la evidencia que `ctx` no cubre.

    El Enriquecedor exige que toda la evidencia tenga un hecho; los datos de
    prueba que se centran en otra cosa necesitan cumplirlo también.
    """
    cubiertos = {i for h in ctx["hechos"] for i in h["evidencia"]}
    faltan = [e.id for e in CASO.evidence if e.id not in cubiertos]
    extra = [{"hecho": f"Relleno de {i}", "evidencia": [i]} for i in faltan]
    return {**ctx, "hechos": ctx["hechos"] + extra}


CONTEXTO_OK = con_cobertura({
    "resumen": "Refacciones Tepalca SA de CV hizo 18 depósitos bajo umbral.",
    "hechos": [
        {"hecho": "Refacciones Tepalca depositó 48,200 MXN", "evidencia": ["ev-001"]},
        {"hecho": "Los 18 depósitos suman 862,300 MXN", "evidencia": ["ev-004"]},
    ],
})

ARGUMENTO_OK = {
    "tesis": "Patrón de fraccionamiento", "confianza": "media",
    "puntos": [{"afirmacion": "18 depósitos casi idénticos en 3 sucursales", "evidencia": ["ev-004"], "politica": ["pol-2.1"]}],
}


class TestEsquemaParaLLM(unittest.TestCase):
    def test_quita_campos_del_codigo_y_referencias(self):
        e = esquema_para_llm(DisposicionV1)
        texto = json.dumps(e)
        for campo in ("presupuesto_agotado", "requiere_confirmacion_humana", "schema_id"):
            self.assertNotIn(campo, e["properties"])
        self.assertNotIn("$ref", texto)
        self.assertNotIn("$defs", texto)
        # Todos los campos visibles son obligatorios, también los anidados.
        self.assertEqual(set(e["required"]), set(e["properties"]))
        punto = e["properties"]["puntos_decisivos"]["items"]
        self.assertIn("politica", punto["required"])

    def test_citas_restringidas_a_ids_del_expediente(self):
        e = esquema_para_llm(ArgumentoV1, ["ev-002", "ev-001"], ["pol-1"])
        punto = e["properties"]["puntos"]["items"]["properties"]
        self.assertEqual(punto["evidencia"]["items"]["enum"], ["ev-001", "ev-002"])
        self.assertEqual(punto["politica"]["items"]["enum"], ["pol-1"])
        self.assertEqual(punto["afirmacion"]["maxLength"], 320)
        self.assertEqual(punto["evidencia"]["maxItems"], 4)

    def test_tope_de_hechos_por_expediente(self):
        e = esquema_para_llm(ContextoV1, max_items={"hechos": 8})
        self.assertEqual(e["properties"]["hechos"]["maxItems"], 8)

    def test_citas_repetidas_se_normalizan(self):
        p = ArgumentoV1.model_validate({**ARGUMENTO_OK, "ronda": 1,
            "puntos": [{"afirmacion": "a", "evidencia": ["ev-001", "ev-002", "ev-001"], "politica": []}]})
        self.assertEqual(p.puntos[0].evidencia, ["ev-001", "ev-002"])

    def test_contexto_no_expone_origen(self):
        hecho = esquema_para_llm(ContextoV1)["properties"]["hechos"]["items"]
        self.assertNotIn("origen", hecho["properties"])


class TestEnriquecedor(unittest.TestCase):
    def test_redacta_nombre_y_marca_procedencia(self):
        r = triage.enriquecer(CASO, llamar=doble(CONTEXTO_OK))
        texto = r.mensaje.resumen + " ".join(h.hecho for h in r.mensaje.hechos)
        self.assertNotIn("Tepalca", texto)
        self.assertIn("SUJ-88210", texto)
        # "refacciones" como palabra común no se toca.
        r2 = triage.enriquecer(CASO, llamar=doble(con_cobertura({
            "resumen": "Tepalca vende refacciones.",
            "hechos": [{"hecho": "Factura por refacciones para flotilla", "evidencia": ["ev-006"]}]})))
        self.assertEqual(r2.mensaje.resumen, "SUJ-88210 vende refacciones.")
        self.assertIn("refacciones para flotilla", r2.mensaje.hechos[0].hecho)
        # ev-001 es externa, ev-004 interna: lo decide el código.
        self.assertEqual([h.origen for h in r.mensaje.hechos[:2]], ["external", "internal"])

    def test_el_enriquecedor_usa_el_modelo_local(self):
        llamar = doble(CONTEXTO_OK)
        with unittest.mock.patch.dict(os.environ, {"LLM_LOCAL_MODELO": "local-7b", "LLM_GRANDE_MODELO": "grande-32b"}):
            triage.enriquecer(CASO, llamar=llamar)
        self.assertEqual(llamar.llamadas[0]["model"], "local-7b")

    def test_exige_cobertura_de_toda_la_evidencia(self):
        # Primer intento omite evidencia -> se reintenta pidiendo lo que falta.
        parcial = {"resumen": "x", "hechos": [{"hecho": "h", "evidencia": ["ev-001"]}]}
        llamar = doble(parcial, CONTEXTO_OK)
        r = triage.enriquecer(CASO, llamar=llamar)
        self.assertEqual(r.intentos, 2)
        self.assertIn("ev-008", llamar.llamadas[1]["mensajes"][-1]["content"])

    def test_reintenta_si_la_respuesta_no_valida_y_suma_tokens(self):
        malo = {"resumen": "x", "hechos": []}  # hechos vacío: no valida
        r = triage.enriquecer(CASO, llamar=doble(malo, CONTEXTO_OK))
        self.assertEqual(r.intentos, 2)
        self.assertEqual(r.metricas["prompt_tokens"], 200)


class TestRespuestaTruncada(unittest.TestCase):
    def test_error_claro_si_se_acaban_los_tokens(self):
        def llamar(mensajes, esquema, **kw):
            return {"texto": '{"resumen": "cortado', "truncada": True}
        with self.assertRaisesRegex(RuntimeError, "max_tokens"):
            triage.enriquecer(CASO, llamar=llamar)


class TestDebate(unittest.TestCase):
    def setUp(self):
        self.contexto = triage.redactar_sujeto(
            triage.aplicar_procedencia(ContextoV1.model_validate(CONTEXTO_OK), CASO), CASO)

    def test_quienes_debaten_no_ven_nombre_ni_texto_libre(self):
        llamar = doble(ARGUMENTO_OK)
        with unittest.mock.patch.dict(os.environ, {"LLM_GRANDE_MODELO": "grande-32b"}):
            triage.argumentar(CASO, self.contexto, [], ronda=1, llamar=llamar)
        prompt = llamar.llamadas[0]["mensajes"][1]["content"]
        self.assertNotIn("Tepalca", prompt)
        self.assertNotIn("PAGO PROVEEDOR CONSIGNA AGO", prompt)  # free_text original
        self.assertIn("[EXTERNO]", prompt)
        self.assertEqual(llamar.llamadas[0]["model"], "grande-32b")

    def test_la_ronda_la_pone_el_codigo(self):
        r = triage.argumentar(CASO, self.contexto, [], ronda=2, llamar=doble({**ARGUMENTO_OK, "ronda": 1}))
        self.assertIsInstance(r.mensaje, ArgumentoV1)
        self.assertEqual(r.mensaje.ronda, 2)

    def test_el_modelo_no_puede_ocultar_presupuesto_agotado(self):
        disp = {"recomendacion": "escalar", "prevalece": "investigador", "fundamento": "f",
                "puntos_decisivos": [{"afirmacion": "a", "evidencia": ["ev-004"], "politica": []}],
                "presupuesto_agotado": False}
        r = triage.deliberar(CASO, self.contexto, [], presupuesto_agotado=True, llamar=doble(disp))
        self.assertTrue(r.mensaje.presupuesto_agotado)
        self.assertTrue(r.mensaje.requiere_confirmacion_humana)


class TestContextoInsuficiente(unittest.TestCase):
    def test_falla_si_el_prompt_llena_la_ventana(self):
        falso = FastAPI()
        falso.get("/salud")(lambda: {})
        falso.post("/api/chat")(lambda: {"message": {"content": "{}"}, "prompt_eval_count": 8000, "eval_count": 10})
        srv, base = levantar(falso)
        try:
            with self.assertRaises(ContextoInsuficiente):
                call_ollama_estructurado([], {}, model="m", base_url=base, num_ctx=8192, max_tokens=600)
        finally:
            srv.should_exit = True


if __name__ == "__main__":
    unittest.main()
