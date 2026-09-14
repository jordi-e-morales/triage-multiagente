"""
Genera tráfico HTTP de prueba entre pods, SIN llamar al modelo.

Se ejecuta dentro del pod del orquestador:
    kubectl -n agentes exec -i deploy/orquestador -- python - < herramientas/prueba_l7.py

Hace tres peticiones al Registro:
  1. POST /v1/anexar con X-Trace-Id   (lo que haría un agente legítimo)
  2. POST /v1/anexar sin X-Trace-Id   (una escritura que nadie pidió)
  3. GET  /salud                      (sonda)
y escribe el trace_id usado, para buscarlo luego en Hubble.

Deja en el Registro dos anexos del caso "prueba-l7" (vive en memoria; se
borra al reiniciar el pod).
"""
import time
import uuid

import requests

traza = "pruebal7" + uuid.uuid4().hex[:8]
base = "http://registro:8000"
cuerpo = {"case_id": "prueba-l7", "autor": "orquestador", "tipo": "prueba_visibilidad", "contenido": {}}

r1 = requests.post(f"{base}/v1/anexar", json=cuerpo, timeout=10,
                   headers={"X-Trace-Id": traza, "X-Span-Id": "span-prueba-1", "X-Agente-Origen": "orquestador"})
time.sleep(1)
r2 = requests.post(f"{base}/v1/anexar", json=cuerpo, timeout=10, headers={"X-Agente-Origen": "orquestador"})
time.sleep(1)
r3 = requests.get(f"{base}/salud", timeout=10)
print(f"trace_id={traza}")
print(f"con_traza={r1.status_code} sin_traza={r2.status_code} salud={r3.status_code}")
