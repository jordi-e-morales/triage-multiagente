#!/usr/bin/env bash
#
# Matriz de pruebas de la política estricta, sin llamar al modelo.
# Para cada par (origen, petición) compara el resultado con lo esperado:
#   PASA    = la red dejó llegar la petición al servicio (422/404/200)
#   L7      = Envoy la bloqueó con 403
#   L4      = la conexión no se pudo establecer (política de salida)
#
# Uso (en la VM, desde la raíz del repo):  bash herramientas/probar_politica.sh
set -u
SONDA="$(cat "$(dirname "$0")/sonda_http.py")"
fallas=0

clasificar() {
  case "$1" in
    403) echo L7 ;;
    sin_conexion*) echo L4 ;;
    *) echo PASA ;;
  esac
}

probar() {   # origen  esperado  METODO  URL
  local origen=$1 esperado=$2 metodo=$3 url=$4
  local salida resultado obtenido
  salida=$(echo "$metodo $url" | kubectl -n agentes exec -i "deploy/$origen" -- python -c "$SONDA" 2>&1 | tail -1)
  resultado=${salida##*-> }
  obtenido=$(clasificar "$resultado")
  if [ "$obtenido" = "$esperado" ]; then marca="ok  "; else marca="FALLA"; fallas=$((fallas+1)); fi
  printf '%s %-12s %-5s %-44s esperado=%-4s obtenido=%-4s (%s)\n' "$marca" "$origen" "$metodo" "$url" "$esperado" "$obtenido" "$resultado"
}

echo "=== Aristas de la tabla (deben PASAR)"
probar orquestador  PASA POST http://enriquecedor:8000/v1/enriquecer
probar orquestador  PASA POST http://investigador:8000/v1/argumentar
probar orquestador  PASA POST http://defensor:8000/v1/objetar
probar orquestador  PASA POST http://arbitro:8000/v1/deliberar
probar investigador PASA POST http://defensor:8000/v1/objetar
probar defensor     PASA POST http://investigador:8000/v1/argumentar
probar enriquecedor PASA POST http://registro:8000/v1/anexar
probar arbitro      PASA POST http://registro:8000/v1/disponer
probar ui           PASA POST http://orquestador:8000/v1/casos
probar ui           PASA GET  http://observador:8000/v1/estado
# Con query string: la regla L7 compara la ruta completa (bug encontrado así).
probar ui           PASA GET  "http://observador:8000/v1/eventos?desde_ms=0&trace_id=x"
probar ui           PASA GET  http://registro:8000/salud

echo "=== El Demo 2: arista legítima, ruta ilegítima (debe ser 403 de capa 7)"
probar enriquecedor L7   POST http://registro:8000/v1/disponer
probar investigador L7   POST http://registro:8000/v1/disponer
probar orquestador  L7   POST http://registro:8000/v1/disponer

echo "=== Rutas no contratadas en aristas existentes (403)"
probar orquestador  L7   GET  http://enriquecedor:8000/docs
probar defensor     L7   POST http://investigador:8000/v1/objetar

echo "=== Aristas que no existen (bloqueo de salida L3/L4)"
probar enriquecedor L4   POST http://investigador:8000/v1/argumentar
probar enriquecedor L4   POST http://arbitro:8000/v1/deliberar
probar registro     L4   POST http://arbitro:8000/v1/deliberar
probar investigador L4   POST http://enriquecedor:8000/v1/enriquecer

echo "=== Salida a internet (exfiltración)"
probar enriquecedor L4   GET  https://example.com/
probar orquestador  L4   GET  https://example.com/

echo ""
if [ "$fallas" -eq 0 ]; then echo "TODAS LAS PRUEBAS PASARON"; else echo "FALLAS: $fallas"; fi
exit "$fallas"
