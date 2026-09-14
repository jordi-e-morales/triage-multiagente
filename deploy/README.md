# deploy/

Manifiestos de Kubernetes de la demo. El entorno (VM, kind, Cilium) lo instala
`lab/` en el repo ConnectLatam26; aquí solo va lo que corre encima.

## Orden

```bash
# 1. Imágenes (dentro de la VM, desde la raíz del repo)
docker build -t triage-agentes:0.4.0 .
docker build -f Dockerfile.ui -t triage-ui:0.4.0 .
kind load docker-image triage-agentes:0.4.0 triage-ui:0.4.0 --name agentes --nodes agentes-worker

# 2. Todo lo de deploy/k8s
kubectl apply -f deploy/k8s/

# 3. Esperar a Ollama y a que baje los modelos
kubectl -n agentes rollout status deploy/ollama
kubectl -n agentes wait --for=condition=complete job/ollama-descarga --timeout=1500s

# 4. Comprobar desde dentro del cluster que todo responde
kubectl -n agentes exec deploy/orquestador -- python -m servicios.verificar

# 5. Abrir la UI desde Windows (escucha en la IP de la VM)
kubectl -n agentes port-forward --address 0.0.0.0 svc/ui 8501:8501
```

`kubectl apply -f deploy/k8s/` aplica en orden alfabético: `agentes.yaml` va
antes que `endpoints.yaml`, así que los pods pueden quedar unos segundos en
`CreateContainerConfigError` hasta que exista el ConfigMap; se recuperan solos.
El Job de descarga también reintenta solo si arranca antes que el servidor.

Si reinicias un pod, el `port-forward` que apuntaba a él se corta: vuelve a
lanzarlo.

## Políticas de Cilium (se aplican a mano)

`deploy/k8s/politicas/` no entra en `kubectl apply -f deploy/k8s/`, a propósito:
una política cambia qué tráfico pasa.

```bash
# Visibilidad L7 (Fase 2): Hubble ve método, ruta y X-Trace-Id. No bloquea nada legítimo.
kubectl apply -f deploy/k8s/politicas/visibilidad-l7.yaml
# Comprobar con tráfico de prueba (no llama al modelo):
kubectl -n agentes exec -i deploy/orquestador -- python - < herramientas/prueba_l7.py
```

Requiere `envoy.streamIdleTimeoutDurationSeconds=1800` en Cilium (lo pone
`lab/cluster-up.sh`): con el valor por omisión, Envoy corta a los 300 s una
llamada a un agente que todavía no responde, y en CPU tardan más.

## Archivos

| Archivo | Qué crea |
|---|---|
| `k8s/00-namespace.yaml` | Namespace `agentes` |
| `k8s/endpoints.yaml` | ConfigMap: URLs, modelos, `num_ctx`, presupuesto de tokens, timeouts |
| `k8s/agentes.yaml` | Deployment + Service de orquestador, enriquecedor, investigador, defensor, arbitro y registro |
| `k8s/ui.yaml` | Deployment + Service de la UI (Streamlit) |
| `k8s/ollama.yaml` | Volumen para modelos, Deployment y Service `ollama` (solo desarrollo, CPU) |
| `k8s/ollama-descarga.yaml` | Job que baja los modelos nombrados en `endpoints` |

## Medido en la VM de desarrollo

VM con 12 vCPU sin GPU (2026-09-13/14). Se midió con 14 GB; desde el 14 de
septiembre la VM usa 10 GB, porque con 14 GB reservados Windows se quedó sin
memoria. Con 10 GB, el límite de Ollama es 7Gi (pendiente de probar una
deliberación completa con ese límite).

- Imagen `ollama/ollama:0.34.0`: 3.45 GB comprimida, ~5.5 GB en disco del nodo.
- `qwen2.5:7b` (4.7 GB): el modelo de desarrollo. `qwen2.5:3b` no sostenía los
  roles del debate.
- Deliberación completa de `aml-0042` por los pods: 12,760 tokens, ~19 min.
  Entre 1.5 y 6 min por agente.
- Imagen `triage-agentes`: 213 MB en disco. Imagen `triage-ui`: 788 MB en disco
  (182 MB comprimida). Versiones exactas de la UI en `requirements-ui.lock.txt`.
- Límite de contexto del modelo: 32 768 tokens. `num_ctx` se fija en cada
  llamada; si un prompt no cabe, la llamada falla en vez de recortar.

## En dCloud

`ollama.yaml` y `ollama-descarga.yaml` no se aplican. Se editan
`LLM_LOCAL_*` y `LLM_GRANDE_*` en `endpoints.yaml` para apuntar a vLLM, y se
comprueba con la página Admin.
