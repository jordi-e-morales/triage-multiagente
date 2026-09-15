#!/usr/bin/env bash
# Apaga las instancias de vLLM del host y las quita del cluster.
#   bash deploy/vllm-host/vllm-down.sh
set -euo pipefail

echo ">> quitando del cluster (Services y Endpoints)"
kubectl -n agentes delete endpoints vllm-local vllm-grande --ignore-not-found
kubectl -n agentes delete service   vllm-local vllm-grande --ignore-not-found

echo ">> deteniendo contenedores"
docker rm -f vllm-local vllm-grande >/dev/null 2>&1 || true

echo "Listo. (El caché de pesos en ~/.cache/huggingface se conserva.)"
