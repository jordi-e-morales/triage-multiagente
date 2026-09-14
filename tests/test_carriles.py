"""
Pruebas de la alineación de los dos carriles.

    python -m unittest tests.test_carriles -v
"""
import unittest

from protocols.carriles import alinear, resumen


def llamada(ts, origen, destino, ruta, trace="T1"):
    return {"ts_ms": ts, "origen": origen, "destino": destino, "ruta": ruta, "trace_id": trace,
            "span_id": f"s{ts}", "estado_http": 200}


def evento_l7(ts, origen, destino, url, trace, verdict="FORWARDED"):
    return {"timestamp_ms": ts, "layer": "cilium", "source": f"agentes/{origen}", "verdict": verdict,
            "action": f"POST {url}", "trace_id": trace, "sin_traza": trace is None,
            "detail": {"destino": f"agentes/{destino}", "visibilidad": "L7"}}


def evento_l34(ts, origen, destino):
    return {"timestamp_ms": ts, "layer": "cilium", "source": f"agentes/{origen}", "verdict": "FORWARDED",
            "action": f"TCP → agentes/{destino}:8000", "trace_id": None, "sin_traza": True,
            "detail": {"destino": f"agentes/{destino}", "visibilidad": "L3_L4"}}


class TestAlinear(unittest.TestCase):
    def test_caso_limpio_todo_emparejado(self):
        ll = [llamada(1, "orquestador", "enriquecedor", "/v1/enriquecer"),
              llamada(2, "enriquecedor", "registro", "/v1/anexar")]
        ev = [evento_l7(3, "enriquecedor", "registro", "http://registro:8000/v1/anexar", "T1"),
              evento_l7(1, "orquestador", "enriquecedor", "http://enriquecedor:8000/v1/enriquecer", "T1")]
        filas = alinear(ll, ev)
        self.assertEqual(resumen(filas), {"par": 2, "sin_evento": 0, "huerfano": 0, "l34": 0})

    def test_la_alarma_del_demo_2(self):
        # El Enriquecedor intenta /v1/disponer sin traza: nadie lo declaró.
        ll = [llamada(1, "enriquecedor", "registro", "/v1/anexar")]
        ev = [evento_l7(1, "enriquecedor", "registro", "http://registro:8000/v1/anexar", "T1"),
              evento_l7(5, "enriquecedor", "registro", "http://registro:8000/v1/disponer", None, "HTTP_403")]
        filas = alinear(ll, ev)
        huerfanos = [f for f in filas if f["tipo"] == "huerfano"]
        self.assertEqual(len(huerfanos), 1)
        self.assertEqual(huerfanos[0]["evento"]["verdict"], "HTTP_403")

    def test_no_alinea_por_tiempo(self):
        # Mismo destino y ruta, misma hora, pero otra traza: NO es pareja.
        ll = [llamada(10, "orquestador", "arbitro", "/v1/deliberar", trace="T1")]
        ev = [evento_l7(10, "orquestador", "arbitro", "http://arbitro:8000/v1/deliberar", "OTRA")]
        self.assertEqual(resumen(alinear(ll, ev)), {"par": 0, "sin_evento": 1, "huerfano": 1, "l34": 0})

    def test_ruta_distinta_con_misma_traza_no_es_pareja(self):
        # La arista es legítima (enriquecedor -> registro) pero la ruta no.
        ll = [llamada(1, "enriquecedor", "registro", "/v1/anexar")]
        ev = [evento_l7(1, "enriquecedor", "registro", "http://registro:8000/v1/disponer", "T1")]
        self.assertEqual(resumen(alinear(ll, ev))["huerfano"], 1)

    def test_l34_nunca_es_alarma(self):
        ll = [llamada(1, "orquestador", "enriquecedor", "/v1/enriquecer")]
        filas = alinear(ll, [evento_l34(1, "orquestador", "enriquecedor")])
        self.assertEqual(resumen(filas), {"par": 0, "sin_evento": 1, "huerfano": 0, "l34": 1})

    def test_orden_por_hora(self):
        ll = [llamada(5, "a", "b", "/x"), llamada(1, "a", "c", "/y")]
        self.assertEqual([f["ts_ms"] for f in alinear(ll, [])], [1, 5])


if __name__ == "__main__":
    unittest.main()
