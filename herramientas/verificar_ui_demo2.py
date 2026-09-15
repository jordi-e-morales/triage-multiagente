from streamlit.testing.v1 import AppTest
import textwrap

SCRIPT = r"""
    import sys
    sys.path.insert(0, "/app")
    from pages.deliberacion import _panel_demo2

    crudo = {"seguridad": [
        {"capa":"content","paso":"guardrail","verdict":"DROPPED","fragmento":"ev-009",
         "detalle":"El guardrail detuvo la inyeccion. Guardrail abierto (sustituto de Cisco AI Defense)"}]}
    ofuscado = {"seguridad": [
        {"capa":"content","paso":"guardrail","verdict":"FORWARDED","fragmento":"ev-009",
         "detalle":"El guardrail dejo pasar la inyeccion."},
        {"capa":"content","paso":"disponer","verdict":"BLOQUEADA","fragmento":"ev-009",
         "detalle":"HTTPError: 403 Client Error: Forbidden for url: http://registro:8000/v1/disponer"},
        {"capa":"content","paso":"ejecutar","verdict":"BLOQUEADA","fragmento":"ev-009",
         "detalle":"RuntimeError: proceso terminado (rc=-9, SIGKILL/kernel senal 9)"}]}
    import streamlit as st
    st.header("CRUDO"); _panel_demo2(crudo)
    st.header("OFUSCADO"); _panel_demo2(ofuscado)
"""

at = AppTest.from_string(textwrap.dedent(SCRIPT), default_timeout=60).run()
assert not at.exception, [e.value for e in at.exception]
html = "".join(m.value for m in at.markdown)
checks = {
    "sin excepciones": not at.exception,
    "tres capas nombradas": all(x in html for x in ("Contenido", "Red", "Kernel")),
    "crudo: contenido DETUVO": "DETUVO" in html,
    "ofuscado: contenido DEJO PASAR": "DEJ" in html and "PASAR" in html,
    "red: 403": "403" in html,
    "kernel: SIGKILL": "SIGKILL" in html,
    "etiqueta sustituto AI Defense": "Cisco AI Defense" in html,
    "sin alarma NO DETUVO (nada se ejecuto)": "NO DETUV" not in html,
}
for k, v in checks.items():
    print(("ok   " if v else "FALLA"), k)
assert all(checks.values())
