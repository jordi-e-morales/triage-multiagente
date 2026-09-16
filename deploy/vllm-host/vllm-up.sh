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

# Local: el 7B en AWQ (4 bits), repo oficial. Se eligió AWQ y no FP8 porque el
# FP8 dinámico obliga a vLLM a cargar el bf16 (~15 GB) y comprimir: ese pico no
# cabe compartiendo GPU con el 32B. AWQ carga ya cuantizado (~5.5 GB), sin pico,
# y cumple la intención del plan (un local pequeño y barato, CLAUDE.md §8).
MODELO_LOCAL="${VLLM_MODELO_LOCAL:-Qwen/Qwen2.5-7B-Instruct-AWQ}"
QUANT_LOCAL="${VLLM_QUANT_LOCAL:-awq_marlin}"
# Grande: el 32B ya cuantizado a 4 bits (AWQ), repo oficial.
MODELO_GRANDE="${VLLM_MODELO_GRANDE:-Qwen/Qwen2.5-32B-Instruct-AWQ}"

PUERTO_LOCAL="${VLLM_PUERTO_LOCAL:-18001}"     # 7B  (Enriquecedor)
PUERTO_GRANDE="${VLLM_PUERTO_GRANDE:-18000}"   # 32B (Investigador/Defensor/Árbitro)

# Fracción del L40S (48 GB) por instancia = pesos + caché KV. El local necesita
# caché grande porque ve el expediente completo (~40k); el grande más aún: sus
# pesos (~19 GB AWQ) + buffers + grafos CUDA topan su propio techo antes de la
# caché, así que necesita la fracción mayor.
# Con el local en AWQ (~5.5 GB) le sobra con poco, así que se le baja para darle
# más al 32B: 0.22 + 0.64 = 0.86; local ~10 GB, grande ~29.4 GB, ~6.4 GB colchón.
# Si el 32B aún da "No available memory for cache blocks": VLLM_EAGER_GRANDE=1,
# o bajar VLLM_CTX_GRANDE, o subir VLLM_FRAC_GRANDE.
FRAC_LOCAL="${VLLM_FRAC_LOCAL:-0.22}"
FRAC_GRANDE="${VLLM_FRAC_GRANDE:-0.64}"

# Ventana de contexto. Los dos modelos comparten 46 GB, así que las ventanas
# COMPITEN: vLLM reserva memoria de activaciones proporcional a max-model-len al
# perfilar la caché. Medido en dCloud: 49k en el 7B + 32k en el 32B NO caben
# juntos (al 7B no le quedaban bloques de caché). Por eso el default es 32k en
# ambos (nativo de Qwen2.5), que arranca holgado.
#
# Para que el Enriquecedor tenga la ventana de ~40k del expediente completo
# (CLAUDE.md §4) hay que hacer sitio, no solo subir CTX_LOCAL. Combinar (el valor
# de VLLM_ROPE_LOCAL es el JSON de ROPE_YARN_49K que se define más abajo):
#   VLLM_CTX_LOCAL=49152 VLLM_KV_DTYPE=fp8 VLLM_CTX_GRANDE=24576 \
#   VLLM_ROPE_LOCAL='{"rope_type":"yarn","factor":2.0,"original_max_position_embeddings":32768}' \
#   bash deploy/vllm-host/vllm-up.sh
# (caché KV en fp8 = la mitad; y bajar la ventana del grande le cede memoria).
# Es calibración de dCloud; se hace cuando existan los expedientes de 40k.
CTX_LOCAL="${VLLM_CTX_LOCAL:-32768}"
CTX_GRANDE="${VLLM_CTX_GRANDE:-32768}"

# dtype de la caché KV. "auto" = como los pesos; "fp8" la reduce a la mitad (útil
# para ganar ventana, a costa de un poco de precisión). Aplica a ambos.
KV_DTYPE="${VLLM_KV_DTYPE:-auto}"

# YaRN para estirar el 7B más allá de 32k. APAGADO por defecto (la ventana por
# defecto es 32k nativo). Receta lista para cuando se suba CTX_LOCAL > 32768:
ROPE_YARN_49K='{"rope_type":"yarn","factor":2.0,"original_max_position_embeddings":32768}'
ROPE_LOCAL="${VLLM_ROPE_LOCAL-}"   # vacío = sin YaRN

CACHE_HF="${VLLM_CACHE_HF:-$HOME/.cache/huggingface}"   # pesos, para no re-bajar
RED_KIND="${VLLM_RED_KIND:-kind}"                       # red Docker del cluster

mkdir -p "$CACHE_HF"

# ─── Arranque de un contenedor de vLLM ───────────────────────────────────────
arrancar() {
  local nombre="$1" modelo="$2" puerto="$3" frac="$4" ctx="$5"; shift 5
  echo ">> $nombre: $modelo  (host :$puerto, VRAM $frac)"
  docker rm -f "$nombre" >/dev/null 2>&1 || true
  # SIN --restart: si el arranque falla (p.ej. no cabe la caché), el contenedor
  # se queda muerto y no entra en bucle reintentando y llenando la VRAM. Cuando
  # la config esté estable se puede añadir "--restart unless-stopped".
  docker run -d --name "$nombre" \
    --gpus all --ipc=host \
    -p "${puerto}:8000" \
    -v "${CACHE_HF}:/root/.cache/huggingface" \
    "$IMAGEN" \
    --model "$modelo" \
    --served-model-name "$modelo" \
    --gpu-memory-utilization "$frac" \
    --max-model-len "$ctx" \
    --kv-cache-dtype "$KV_DTYPE" \
    --enable-prefix-caching \
    "$@" >/dev/null
}

# Ambos en AWQ (kernel marlin). El local lleva YaRN solo si ROPE_LOCAL no está
# vacío (ventana > 32k nativo).
opciones_local=(--quantization "$QUANT_LOCAL")
if [ -n "$ROPE_LOCAL" ]; then
  opciones_local+=(--rope-scaling "$ROPE_LOCAL")
fi
arrancar vllm-local  "$MODELO_LOCAL"  "$PUERTO_LOCAL"  "$FRAC_LOCAL"  "$CTX_LOCAL"  "${opciones_local[@]}"

# El 32B es el que más aprieta. --enforce-eager (VLLM_EAGER_GRANDE=1) libera la
# memoria de los grafos CUDA (~2-3 GB) para la caché KV, a costa de algo de
# velocidad. Útil si da "No available memory for the cache blocks".
opciones_grande=(--quantization awq_marlin)
if [ -n "${VLLM_EAGER_GRANDE:-}" ]; then
  opciones_grande+=(--enforce-eager)
fi
arrancar vllm-grande "$MODELO_GRANDE" "$PUERTO_GRANDE" "$FRAC_GRANDE" "$CTX_GRANDE" "${opciones_grande[@]}"

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
