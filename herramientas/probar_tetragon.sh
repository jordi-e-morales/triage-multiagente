#!/usr/bin/env bash
#
# Prueba la TracingPolicy agentes-sin-exec sin llamar al modelo.
#
#  1. Desde el Python del Enriquecedor intenta ejecutar /bin/sh y un binario
#     copiado con otro nombre. Esperado: el hijo muere con SIGKILL (-9).
#  2. El servicio del Enriquecedor sigue respondiendo.
#  3. Un pod que NO es agente (registro) sí puede ejecutar.
#  4. Guarda los eventos de Tetragon en ~/capturas/tetragon-sigkill.jsonl.
#
# Uso (en la VM, desde la raíz del repo): bash herramientas/probar_tetragon.sh
set -u
fallas=0
nodo_pod=$(kubectl -n agentes get pod -l app=enriquecedor -o jsonpath='{.items[0].spec.nodeName}')
tetragon_pod=$(kubectl -n kube-system get pod -l app.kubernetes.io/name=tetragon \
  --field-selector spec.nodeName="$nodo_pod" -o jsonpath='{.items[0].metadata.name}')

# Eventos del kernel en segundo plano mientras se prueba.
mkdir -p ~/capturas
kubectl -n kube-system exec "$tetragon_pod" -c tetragon -- \
  tetra getevents -o json --namespaces agentes > ~/capturas/tetragon-sigkill.jsonl 2>/dev/null &
lector=$!
sleep 3

# El FS del agente es de solo lectura (no se puede copiar un binario con otro
# nombre), así que se prueban dos binarios distintos ya presentes.
INTENTO='
import subprocess
r1 = subprocess.run(["/bin/sh", "-c", "echo hola"], capture_output=True)
r2 = subprocess.run(["/usr/bin/env"], capture_output=True)
print(r1.returncode, r2.returncode)
'

esperar() {  # descripcion  esperado  obtenido
  if [ "$2" = "$3" ]; then echo "ok    $1 (=$3)"; else echo "FALLA $1: esperado $2, obtenido $3"; fallas=$((fallas+1)); fi
}

echo "=== 1. Enriquecedor (rol=agente) intenta ejecutar"
salida=$(kubectl -n agentes exec deploy/enriquecedor -- python -c "$INTENTO" 2>&1 | tail -1)
esperar "sh desde el agente muere con SIGKILL" "-9" "$(echo "$salida" | awk '{print $1}')"
esperar "otro binario (/usr/bin/env) también muere" "-9" "$(echo "$salida" | awk '{print $2}')"

echo "=== 2. El servicio del Enriquecedor sigue vivo"
estado=$(kubectl -n agentes exec deploy/ui -- python -c "import requests;print(requests.get('http://enriquecedor:8000/salud',timeout=5).status_code)")
esperar "salud del enriquecedor" "200" "$estado"
reinicios=$(kubectl -n agentes get pod -l app=enriquecedor -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}')
echo "      reinicios del contenedor: $reinicios"

echo "=== 3. Registro (no es agente) puede ejecutar"
salida=$(kubectl -n agentes exec deploy/registro -- python -c "import subprocess;print(subprocess.run(['/bin/sh','-c','true']).returncode)" 2>&1 | tail -1)
esperar "sh desde el registro" "0" "$salida"

sleep 3
kill "$lector" 2>/dev/null
echo "=== 4. Eventos de Tetragon con acción SIGKILL"
jq -c 'select(.process_kprobe != null and .process_kprobe.action == "KPROBE_ACTION_SIGKILL")
       | {hora: .time, pod: .process_kprobe.process.pod.name, binario: .process_kprobe.process.binary,
          quiso_ejecutar: .process_kprobe.args[0].linux_binprm_arg.path, politica: .process_kprobe.policy_name}' \
  ~/capturas/tetragon-sigkill.jsonl
n=$(jq -c 'select(.process_kprobe.action == "KPROBE_ACTION_SIGKILL")' ~/capturas/tetragon-sigkill.jsonl | wc -l)
esperar "eventos SIGKILL registrados (al menos 2)" "si" "$([ "$n" -ge 2 ] && echo si || echo no)"

echo ""
if [ "$fallas" -eq 0 ]; then echo "TODAS LAS PRUEBAS PASARON"; else echo "FALLAS: $fallas"; fi
exit "$fallas"
