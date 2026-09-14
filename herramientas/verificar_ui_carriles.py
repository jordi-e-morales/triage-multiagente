"""Verifica el panel de dos carriles dentro de la imagen de la UI con AppTest.

Se ejecuta en el pod:  kubectl -n agentes exec -i deploy/ui -- python - < apptest_carriles.py
No llama a ningún agente ni al modelo.
"""
from streamlit.testing.v1 import AppTest


SCRIPT = r"""
    import sys
    sys.path.insert(0, "/app")
    from pages._pipeline_view import render_dos_carriles

    llamadas = [
        {"ts_ms": 1, "origen": "orquestador", "destino": "enriquecedor", "ruta": "/v1/enriquecer",
         "metodo": "POST", "trace_id": "T1aaaaaaaaaaaa", "span_id": "a", "estado_http": 200},
        {"ts_ms": 2, "origen": "enriquecedor", "destino": "registro", "ruta": "/v1/anexar",
         "metodo": "POST", "trace_id": "T1aaaaaaaaaaaa", "span_id": "b", "estado_http": 200},
    ]
    eventos = [
        {"timestamp_ms": 2, "layer": "cilium", "source": "agentes/enriquecedor", "verdict": "FORWARDED",
         "action": "POST http://registro:8000/v1/anexar", "trace_id": "T1aaaaaaaaaaaa", "sin_traza": False,
         "detail": {"destino": "agentes/registro", "visibilidad": "L7"}},
        {"timestamp_ms": 3, "layer": "cilium", "source": "agentes/enriquecedor", "verdict": "HTTP_403",
         "action": "POST http://registro:8000/v1/disponer<script>alert(1)</script>", "trace_id": None,
         "sin_traza": True, "detail": {"destino": "agentes/registro", "visibilidad": "L7"}},
        {"timestamp_ms": 4, "layer": "cilium", "source": "agentes/orquestador", "verdict": "FORWARDED",
         "action": "TCP → agentes/enriquecedor:8000", "trace_id": None, "sin_traza": True,
         "detail": {"destino": "agentes/enriquecedor", "visibilidad": "L3_L4"}},
    ]
    render_dos_carriles(llamadas, eventos, "nota de prueba")
"""


import textwrap
at = AppTest.from_string(textwrap.dedent(SCRIPT), default_timeout=60).run()
assert not at.exception, [e.value for e in at.exception]
html = "".join(m.value for m in at.markdown)
comprobaciones = {
    "sin excepciones": not at.exception,
    "resumen 1 par / 1 sin evento / 1 huérfano / 1 L3-L4":
        "1 emparejados por traza · 1 llamadas sin evento de red · 1 eventos sin contraparte · 1 flujos L3/L4"
        in "".join(c.value for c in at.caption),
    "marca SIN CONTRAPARTE": "SIN CONTRAPARTE" in html,
    "carril izquierdo con la arista": "orquestador → enriquecedor" in html,
    "<script> escapado": "&lt;script&gt;" in html and "<script>" not in html,
    "nota de fuente visible": any("nota de prueba" in i.value for i in at.info),
    "expander L3/L4": any("capa 3/4" in x.label for x in at.expander),
}
for nombre, ok in comprobaciones.items():
    print(("ok   " if ok else "FALLA"), nombre)
assert all(comprobaciones.values())
