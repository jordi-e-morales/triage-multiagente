"""
Prueba el catálogo de endpoints y el verificador de la página Admin.

Los servidores de modelos se sustituyen por apps mínimas que responden con la
misma forma que Ollama (/api/tags) y vLLM (/v1/models). Es un doble de prueba
del verificador, no del demo: lo único que se prueba aquí es que el Admin
interpreta bien las dos respuestas.

    python -m unittest tests.test_verificar -v
"""
import os
import unittest
from unittest import mock

from fastapi import FastAPI

from servicios import config
from servicios.registro import app as registro_app
from servicios.verificar import verificar_modelo, verificar_servicio
from tests._servidor import levantar, puerto_libre

ollama_falso = FastAPI()
ollama_falso.get("/api/tags")(lambda: {"models": [{"name": "qwen2.5:3b"}]})

vllm_falso = FastAPI()
vllm_falso.get("/v1/models")(lambda: {"data": [{"id": "Qwen/Qwen2.5-32B-Instruct-AWQ"}]})


class TestConfig(unittest.TestCase):
    def test_valores_por_omision_son_nombres_de_service(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.url_de("registro"), "http://registro:8000")
            self.assertTrue(config.admin_visible())

    def test_variables_de_entorno_mandan(self):
        with mock.patch.dict(os.environ, {"URL_REGISTRO": "http://10.0.0.5:9000",
                                          "LLM_GRANDE_MODELO": "qwen32b", "MOSTRAR_ADMIN": "0"}):
            self.assertEqual(config.url_de("registro"), "http://10.0.0.5:9000")
            self.assertEqual(config.modelos()[1].modelo, "qwen32b")
            self.assertFalse(config.admin_visible())

    def test_catalogo_coincide_con_el_configmap(self):
        # Si alguien agrega una variable en un lado y no en el otro, falla aquí.
        ruta = os.path.join(os.path.dirname(os.path.dirname(__file__)), "deploy", "k8s", "endpoints.yaml")
        with open(ruta, encoding="utf-8") as f:
            yaml_txt = f.read()
        variables = [s.variable for s in config.servicios()]
        for m in config.modelos():
            variables += [m.variable_url, m.variable_modelo]
        for v in variables + ["MOSTRAR_ADMIN", "LLM_NUM_CTX"]:
            self.assertIn(f"{v}:", yaml_txt, f"falta {v} en endpoints.yaml")


class TestVerificar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidores = []
        for nombre, app, ruta in [("registro", registro_app, "/salud"),
                                  ("ollama", ollama_falso, "/api/tags"),
                                  ("vllm", vllm_falso, "/v1/models")]:
            srv, base = levantar(app, ruta)
            cls.servidores.append(srv)
            setattr(cls, f"url_{nombre}", base)

    @classmethod
    def tearDownClass(cls):
        for s in cls.servidores:
            s.should_exit = True

    def test_servicio_que_responde(self):
        r = verificar_servicio(config.Servicio("registro", "URL_REGISTRO", self.url_registro))
        self.assertTrue(r.ok, r.detalle)

    def test_servicio_apagado(self):
        r = verificar_servicio(config.Servicio("x", "X", f"http://127.0.0.1:{puerto_libre()}"))
        self.assertFalse(r.ok)
        self.assertTrue(r.detalle.startswith("conexión rechazada"), r.detalle)

    def test_nombre_que_no_resuelve(self):
        r = verificar_servicio(config.Servicio("x", "X", "http://servicio-inexistente.invalid:8000"))
        self.assertFalse(r.ok)
        self.assertTrue(r.detalle.startswith("no resuelve"), r.detalle)

    def test_ollama_con_el_modelo(self):
        m = config.Modelo("local", "enriquecedor", "U", self.url_ollama, "M", "qwen2.5:3b")
        self.assertTrue(verificar_modelo(m).ok)

    def test_ollama_sin_el_modelo_dice_que_tiene(self):
        m = config.Modelo("local", "enriquecedor", "U", self.url_ollama, "M", "llama3:8b")
        r = verificar_modelo(m)
        self.assertFalse(r.ok)
        self.assertEqual(r.modelos_disponibles, ["qwen2.5:3b"])

    def test_vllm(self):
        m = config.Modelo("grande", "arbitro", "U", self.url_vllm, "M", "Qwen/Qwen2.5-32B-Instruct-AWQ")
        self.assertTrue(verificar_modelo(m).ok)


if __name__ == "__main__":
    unittest.main()
