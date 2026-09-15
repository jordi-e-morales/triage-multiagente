#!/usr/bin/env bash
# Levanta las DOS instancias de vLLM en el HOST de dCloud (Camino B), sobre el
# único L40S, y las publica dentro del cluster de kind como Services.
#
# Por qué en el host y no en pods: meter la GPU dentro de kind (device plugin +
# time-slicing) es la pieza más frágil del proyecto. vLLM en el host es lo que
# el propio CLAUDE.md §8 ya permite ("correr Ollama en el host y apuntar los
# pods a la IP del host"). Los agentes siguen llamando a http://vllm-local:8000
# y http://vllm-grande:8000: esos Services (servicios.yaml) redirigen al host.
#
# Reparto del L40S (48 GB): cada instancia toma su fracción de VRAM al arrancar
# (pesos + caché KV). No hace falta MPS; el planificador de la GPU intercala el
# cómputo. Calibrar las fracciones si el 32B no arranca.
#
# La separación de la matriz de permisos (Enriquecedor -> solo local; los que
# debaten -> solo grande) se hace por PUERTO del host: local 18001, grande
# 18000. La política de egress (politicas/vllm-host-egress.yaml) lo acota.
#
# Reproducible: este script es el artefacto. Tras la reconstrucción de cero del
# lab, se vuelve a correr tal cual (los pesos se re-descargan al caché del host).
#
#   bash deploy/vllm-host/vllm-up.sh
set -euo pipefail

# ─── Configuración (sobrescribible por variable de entorno) ──────────────────
IMAGEN="${VLLM_IMAGEN:-vllm/vllm-openai:v0.6.6.post1}"   # FIJA. No :latest.

MODELO_LOCAL="${VLLM_MODELO_LOCAL:-Qwen/Qwen2.5-7B-Instruct-FP8}"
MODELO_GRANDE="${VLLM_MODELO_GRANDE:-Qwen/Qwen2.5-32B-Instruct-AWQ}"

PUERTO_LOCAL="${VLLM_PUERTO_LOCAL:-18001}"     # 7B  (Enriquecedor)
PUERTO_GRANDE="${VLLM_PUERTO_GRANDE:-18000}"   # 32B (Investigador/Defensor/Árbitro)

# Fracción del L40S por instancia. 0.22 + 0.55 = 0.77; queda ~11 GB de colchón.
FRAC_LOCAL="${VLLM_FRAC_LOCAL:-0.22}"
FRAC_GRANDE="${VLLM_FRAC_GRANDE:-0.55}"

CTX_LOCAL="${VLLM_CTX_LOCAL:-8192}"
CTX_GRANDE="${VLLM_CTX_GRANDE:-16384}"

CACHE_HF="${VLLM_CACHE_HF:-$HOME/.cache/huggingface}"   # pesos, para no re-bajar
RED_KIND="${VLLM_RED_KIND:-kind}"                       # red Docker del cluster

mkdir -p "$CACHE_HF"

# ─── Arranque de un contenedor de vLLM ───────────────────────────────────────
arrancar() {
  local nombre="$1" modelo="$2" puerto="$3" frac="$4" ctx="$5"; shift 5
  echo ">> $nombre: $modelo  (host :$puerto, VRAM $frac)"
  docker rm -f "$nombre" >/dev/null 2>&1 || true
  docker run -d --name "$nombre" \
    --gpus all --ipc=host --restart unless-stopped \
    -p "${puerto}:8000" \
    -v "${CACHE_HF}:/root/.cache/huggingface" \
    "$IMAGEN" \
    --model "$modelo" \
    --served-model-name "$modelo" \
    --gpu-memory-utilization "$frac" \
    --max-model-len "$ctx" \
    --enable-prefix-caching \
    "$@" >/dev/null
}

# El 7B en FP8 (Ada Lovelace lo soporta); el 32B con AWQ (kernel marlin).
arrancar vllm-local  "$MODELO_LOCAL"  "$PUERTO_LOCAL"  "$FRAC_LOCAL"  "$CTX_LOCAL"  --quantization fp8
arrancar vllm-grande "$MODELO_GRANDE" "$PUERTO_GRANDE" "$FRAC_GRANDE" "$CTX_GRANDE" --quantization awq_marlin

# ─── Esperar a que ambos respondan /health ───────────────────────────────────
esperar() {
  local nombre="$1" puerto="$2" intentos="${3:-120}"
  echo -n ">> esperando a $nombre (puede tardar: baja pesos y carga a VRAM)"
  for _ in $(seq 1 "$intentos"); do
    if curl -sf "http://127.0.0.1:${puerto}/health" >/dev/null 2>&1; then
      echo " OK"; return 0
    fi
    echo -n "."; sleep 10
  done
  echo ""; echo "!! $nombre no respondió. Revisa: docker logs $nombre" >&2; return 1
}
esperar vllm-local  "$PUERTO_LOCAL"
esperar vllm-grande "$PUERTO_GRANDE" 180   # el 32B tarda más

# ─── Publicar dentro del cluster: Services (estáticos) + Endpoints (IP del host)
# El host, visto desde los pods de kind, es la puerta de enlace de la red Docker
# del cluster. Se calcula, no se teclea (cambia en cada reconstrucción).
HOSTIP="$(docker network inspect "$RED_KIND" -f '{{(index .IPAM.Config 0).Gateway}}')"
if [ -z "$HOSTIP" ]; then
  echo "!! No pude obtener la IP del host en la red '$RED_KIND'." >&2; exit 1
fi
echo ">> IP del host para el cluster: $HOSTIP"

DIR="$(cd "$(dirname "$0")" && pwd)"
kubectl apply -f "$DIR/servicios.yaml"

# Endpoints: enlazan cada Service (sin selector) con host:puerto. El nombre del
# Endpoints DEBE coincidir con el del Service para que Kubernetes los una.
kubectl apply -f - <<EOF
apiVersion: v1
kind: Endpoints
metadata:
  name: vllm-local
  namespace: agentes
subsets:
  - addresses: [{ip: "$HOSTIP"}]
    ports: [{port: $PUERTO_LOCAL}]
---
apiVersion: v1
kind: Endpoints
metadata:
  name: vllm-grande
  namespace: agentes
subsets:
  - addresses: [{ip: "$HOSTIP"}]
    ports: [{port: $PUERTO_GRANDE}]
EOF

cat <<EOF

Listo. vLLM corre en el host y el cluster lo ve como vllm-local / vllm-grande.

Siguiente:
  1. Apuntar los agentes a vLLM en deploy/k8s/endpoints.yaml:
       LLM_BACKEND: "vllm"
       LLM_LOCAL_URL:    "http://vllm-local:8000"
       LLM_LOCAL_MODELO: "$MODELO_LOCAL"
       LLM_GRANDE_URL:    "http://vllm-grande:8000"
       LLM_GRANDE_MODELO: "$MODELO_GRANDE"
     kubectl apply -f deploy/k8s/endpoints.yaml
     kubectl -n agentes rollout restart deploy

  2. Permitir el egress a los modelos en el host (puertos $PUERTO_LOCAL/$PUERTO_GRANDE):
     kubectl apply -f deploy/k8s/politicas/vllm-host-egress.yaml

  3. Probar:  curl -s http://127.0.0.1:$PUERTO_GRANDE/v1/models | head
     Apagar:  bash deploy/vllm-host/vllm-down.sh
EOF
