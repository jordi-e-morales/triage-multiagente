#!/usr/bin/env bash
# Aplica el egress de los agentes hacia vLLM en el host, con la IP REAL de la
# gateway de kind (toCIDRSet), no `toEntities: [host]`.
#
# Por qué CIDR y no [host]: medido en dCloud, Cilium en kind NO clasifica la
# puerta de enlace de la red Docker como la entidad `host`, así que una regla
# `toEntities: [host]` no matchea y el egress a los modelos queda en TIMEOUT.
# El CIDR /32 de esa gateway sí funciona. La IP cambia en cada reconstrucción,
# por eso se calcula aquí (no se teclea).
#
# REQUISITO DE ORDEN: base-dns (dentro de estricta.yaml) debe estar aplicado
# ANTES. Al aplicar una política con egress, Cilium pone al pod en default-deny
# de salida; sin la regla de DNS de base-dns, el pod se queda sin resolver
# nombres. Este script lo verifica y avisa.
#
#   bash deploy/vllm-host/egress-up.sh
set -euo pipefail

if ! kubectl -n agentes get ciliumnetworkpolicy base-dns >/dev/null 2>&1; then
  echo "!! Falta base-dns. Aplica primero estricta.yaml, o el DNS se romperá:" >&2
  echo "   kubectl apply -f deploy/k8s/politicas/estricta.yaml" >&2
  exit 1
fi

PUERTO_LOCAL="${VLLM_PUERTO_LOCAL:-18001}"
PUERTO_GRANDE="${VLLM_PUERTO_GRANDE:-18000}"
RED_KIND="${VLLM_RED_KIND:-kind}"

HOSTIP="$(docker network inspect "$RED_KIND" -f '{{range .IPAM.Config}}{{.Gateway}} {{end}}' \
          | tr ' ' '\n' | grep -E '^[0-9]+\.' | head -1)"
if [ -z "$HOSTIP" ]; then
  echo "!! No pude obtener la IP IPv4 de la gateway en la red '$RED_KIND'." >&2; exit 1
fi
echo ">> egress a vLLM en el host $HOSTIP (local :$PUERTO_LOCAL, grande :$PUERTO_GRANDE)"

kubectl apply -f - <<EOF
# Enriquecedor -> modelo local. Se permiten AMBOS puertos (18001 el 7B, 18000 el
# 32B) para que funcione en las dos configuraciones: dos modelos (7B en 18001) o
# el modo temporal donde el 32B hace de local (18000). Ver nota en DCLOUD 5.2.
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata: {name: enriquecedor-vllm-local, namespace: agentes}
spec:
  endpointSelector: {matchLabels: {app: enriquecedor}}
  egress:
    - toCIDRSet: [{cidr: ${HOSTIP}/32}]
      toPorts: [{ports: [{port: "${PUERTO_LOCAL}", protocol: TCP}, {port: "${PUERTO_GRANDE}", protocol: TCP}]}]
---
# Investigador / Defensor / Árbitro -> SOLO el modelo grande (host :$PUERTO_GRANDE)
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata: {name: debatientes-vllm-grande, namespace: agentes}
spec:
  endpointSelector:
    matchExpressions:
      - {key: app, operator: In, values: [investigador, defensor, arbitro]}
  egress:
    - toCIDRSet: [{cidr: ${HOSTIP}/32}]
      toPorts: [{ports: [{port: "${PUERTO_GRANDE}", protocol: TCP}]}]
EOF

echo ">> listo. Prueba: kubectl -n agentes exec deploy/enriquecedor -- \\"
echo "     python -c \"import requests; print(requests.get('http://vllm-local:8000/v1/models', timeout=10).text[:120])\""
