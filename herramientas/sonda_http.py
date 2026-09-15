"""
Sonda HTTP para probar políticas de red SIN llamar al modelo.

Se ejecuta DENTRO de un pod y hace peticiones que no disparan trabajo:
cuerpos vacíos o inválidos, que el servicio rechaza con 422 si la red deja
pasar la petición. Así se distingue:

    403            lo bloqueó la política L7 (Envoy)
    422 / 404 / 200 la red dejó pasar y respondió el servicio
    sin_conexion   bloqueo L3/L4 (la conexión no se establece o se cae)

Uso (lee casos de stdin, uno por línea: METODO URL):
    kubectl -n agentes exec -i deploy/enriquecedor -- python -c "$(cat herramientas/sonda_http.py)" < casos.txt
Imprime:  METODO URL -> resultado
"""
import sys

import requests

for linea in sys.stdin:
    linea = linea.strip()
    if not linea or linea.startswith("#"):
        continue
    metodo, url = linea.split(maxsplit=1)
    try:
        # Cuerpo vacío: si llega al servicio, la validación lo rechaza (422)
        # sin anexar, disponer ni llamar al modelo.
        r = requests.request(metodo, url, json={} if metodo == "POST" else None,
                             headers={"X-Trace-Id": "sonda-politica"}, timeout=5)
        resultado = str(r.status_code)
    except requests.RequestException as e:
        resultado = f"sin_conexion ({type(e).__name__})"
    print(f"{metodo} {url} -> {resultado}", flush=True)
