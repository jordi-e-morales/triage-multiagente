# deploy/

Manifiestos de Kubernetes de la demo. El entorno (VM, kind, Cilium) lo instala
`lab/` en el repo ConnectLatam26; aquí solo va lo que corre encima.

## Orden

```bash
# 1. Namespace, apuntes de endpoints y servidor de modelos
kubectl apply -f deploy/k8s/

# 2. Esperar a que Ollama esté listo y a que baje los modelos
kubectl -n agentes rollout status deploy/ollama
kubectl -n agentes wait --for=condition=complete job/ollama-descarga --timeout=900s
```

`kubectl apply -f deploy/k8s/` aplica los archivos en orden alfabético. El Job
de descarga puede fallar la primera vez si arranca antes que el servidor; se
reintenta solo.

## Archivos

| Archivo | Qué crea |
|---|---|
| `k8s/00-namespace.yaml` | Namespace `agentes` |
| `k8s/endpoints.yaml` | ConfigMap con las URLs de componentes y modelos (lo que muestra la página Admin) |
| `k8s/ollama.yaml` | Volumen para modelos, Deployment y Service `ollama` (solo desarrollo, CPU) |
| `k8s/ollama-descarga.yaml` | Job que baja los modelos nombrados en `endpoints` |

## Medido en la VM de desarrollo (2026-09-13)

- Imagen `ollama/ollama:0.34.0`: 3.45 GB comprimida, ~5.5 GB en disco del nodo.
- `qwen2.5:3b` (Q4_K_M, 1.9 GB): descarga en ~3 min.
- En CPU (4 vCPU): ~9 tokens/s de generación; primera llamada con carga del
  modelo ~9 s, las siguientes ~2 s para una respuesta corta.
- Límite de contexto del modelo: 32 768 tokens. Hay que fijar `num_ctx` en cada
  llamada; si no, Ollama recorta el contexto sin avisar.

## En dCloud

`ollama.yaml` y `ollama-descarga.yaml` no se aplican. Se editan
`LLM_LOCAL_*` y `LLM_GRANDE_*` en `endpoints.yaml` para apuntar a vLLM, y se
comprueba con la página Admin.
