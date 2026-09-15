# Corridas guardadas

Las corridas (deliberaciones) viven en memoria en el Orquestador y el Registro:
si los pods se reinician o la VM se apaga, se pierden. Aquí se guardan las que
vale la pena conservar, en el mismo formato que devuelve
`GET /v1/corridas/{id}`.

Sirven de referencia y son la semilla de los checkpoints de la Fase 5 (modo
presentación), donde cada demo debe poder arrancar de un estado grabado sin
depender de una corrida en vivo.

| Archivo | Qué es |
|---|---|
| `demo2-aml-ofuscado-5829bbfc45f2.json` | Primera corrida completa del Demo 2 en vivo (2026-09-15): guardrail deja pasar la inyección ofuscada, Cilium responde 403 y Tetragon manda SIGKILL; el debate completa y el Árbitro pide información. |

Para guardar una corrida:

```bash
kubectl -n agentes exec deploy/ui -- python -c "import requests,json; \
  print(json.dumps(requests.get('http://orquestador:8000/v1/corridas/<ID>').json(), ensure_ascii=False))" \
  > corrida.json
```
