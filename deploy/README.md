# deploy/

Manifiestos de Kubernetes de la demo. El entorno (VM, kind, Cilium) lo instala
`lab/` en el repo ConnectLatam26; aquí solo va lo que corre encima.

## Orden

```bash
# 1. Imágenes (dentro de la VM, desde la raíz del repo)
docker build -t triage-agentes:0.6.0 .
docker build -f Dockerfile.ui -t triage-ui:0.6.0 .
kind load docker-image triage-agentes:0.6.0 triage-ui:0.6.0 --name agentes --nodes agentes-worker

# 2. Todo lo de deploy/k8s
kubectl apply -f deploy/k8s/

# 3. Esperar a Ollama y a que baje los modelos
kubectl -n agentes rollout status deploy/ollama
kubectl -n agentes wait --for=condition=complete job/ollama-descarga --timeout=1500s

# 4. Comprobar desde dentro del cluster que todo responde
#    Desde la UI: con la política estricta es el único pod que puede
#    consultar la salud de todos los componentes.
kubectl -n agentes exec deploy/ui -- python -m servicios.verificar

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
# Fase 3 (vigente): la tabla de contratos. Incluye la visibilidad L7. La
# política de visibilidad sola debe borrarse: Cilium suma políticas y su
# "cualquier HTTP" anularía las restricciones de ruta.
kubectl apply -f deploy/k8s/politicas/estricta.yaml
kubectl delete -f deploy/k8s/politicas/visibilidad-l7.yaml --ignore-not-found
# Comprobar con la matriz (22 casos, no llama al modelo):
bash herramientas/probar_politica.sh

# Fase 2 (histórica): solo visibilidad, sin restringir rutas.
# kubectl apply -f deploy/k8s/politicas/visibilidad-l7.yaml
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

## Validación de la Fase 2 (2026-09-14)

Deliberación `fe2b66485b3f` de `aml-0042` por los pods, con la política de
visibilidad L7 activa, VM de 10 GB y Ollama limitado a 7Gi:

- Completada en 817 s, 17,472 tokens, 14 llamadas entre componentes, todas HTTP 200.
- Dos carriles: **14 emparejados por traza, 0 llamadas sin evento de red,
  0 eventos sin contraparte** (más 35 flujos L3/L4, que no se alinean).
- Sin reintentos de Envoy: 14 peticiones L7 observadas = 14 declaradas.
- La llamada más larga fue de 255 s, así que el ajuste de 300 s a 1800 s del
  proxy **no llegó a ponerse a prueba** en esta corrida.

## Validación del Demo 2 en vivo (2026-09-15)

Corrida `5829bbfc45f2` de `aml-ofuscado` por la UI/orquestador, con guardrail,
política estricta y Tetragon activos (VM de 10 GB):

- Las tres capas atraparon lo suyo, con datos reales en el panel:
  - Contenido (guardrail): DEJÓ PASAR la inyección ofuscada (falla a propósito).
  - Red (Cilium L7): 403 al intentar `POST /v1/disponer`.
  - Kernel (Tetragon): SIGKILL (señal 9) al intentar ejecutar.
- El debate completó igual (866 s, 17,853 tokens) y el Árbitro dispuso
  `pedir_informacion`, pendiente de confirmación humana.
- Sin reinicios de pods pese a la RAM muy justa (pico ~148 MB libres): el 7B y
  el guardrail conviven en 10 GB, pero al límite. En dCloud sobra memoria.
- Nota honesta: el documento envenenado (ev-009) se normalizó como un hecho y
  el debate llegó a citarlo. Las ACCIONES se bloquearon, pero el TEXTO de la
  inyección sí entró al contexto del razonamiento. Endurecerlo (no dejar que
  un texto externo con directiva se convierta en hecho citable) queda como
  mejora futura.

## En dCloud

`ollama.yaml` y `ollama-descarga.yaml` no se aplican. Se editan
`LLM_LOCAL_*` y `LLM_GRANDE_*` en `endpoints.yaml` para apuntar a vLLM, y se
comprueba con la página Admin.
