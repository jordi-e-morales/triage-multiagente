# Puesta en marcha en dCloud

Pasos para levantar la demo en el servidor de dCloud (L40S) desde cero,
clonando de GitHub. Todo corre dentro de dCloud; la laptop solo abre el
navegador.

## 1. Clonar los dos repos

```bash
git clone https://github.com/jordi-e-morales/connect26-demo.git
git clone https://github.com/jordi-e-morales/triage-multiagente.git
```

## 2. Entorno y cluster (repo connect26-demo)

```bash
cd connect26-demo/lab
chmod +x *.sh
./bootstrap.sh      # docker, kubectl, kind, cilium, hubble, helm (verifica BTF)
# cerrar sesión y volver a entrar para usar docker sin sudo, luego:
./cluster-up.sh     # kind + Cilium (con el timeout de Envoy) + Hubble
./tetragon-up.sh    # control de kernel
```

Si tras un reinicio el cluster queda colgado: `./reparar-cluster.sh`.

## 3. Modelo del guardrail (gated, NO está en git)

El clasificador Llama Prompt Guard 2 (22M) es gated de Meta y no se sube a
GitHub. Descárgalo con tu cuenta (una vez) y déjalo en `triage-multiagente/modelo`:

```bash
pip install -U "huggingface_hub[cli]"
huggingface-cli login          # pega tu token de Hugging Face
huggingface-cli download meta-llama/Llama-Prompt-Guard-2-22M \
  --local-dir triage-multiagente/modelo
```

(Requiere aceptar la licencia en huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M.)

## 4. Construir imágenes y desplegar (repo triage-multiagente)

```bash
cd triage-multiagente
docker build -t triage-agentes:0.6.0 .
docker build -f Dockerfile.ui -t triage-ui:0.6.0 .
docker build -f Dockerfile.guardrail -t triage-guardrail:0.5.0 .   # usa ./modelo
kind load docker-image triage-agentes:0.6.0 triage-ui:0.6.0 triage-guardrail:0.5.0 \
  --name agentes --nodes agentes-worker

kubectl apply -f deploy/k8s/                 # namespace, endpoints, agentes, ui, ollama, observador
kubectl apply -f deploy/k8s/guardrail.yaml
```

## 5. Modelo de lenguaje: aquí sí hay GPU (Fase 4)

En el lab local se usa Ollama en CPU (`deploy/k8s/ollama.yaml`). En dCloud eso
se sustituye por vLLM en la L40S. El código y los manifiestos ya están (backend
vLLM en `agents/llm_provider.py`, contador de costo en `agents/costos.py`,
`deploy/k8s/vllm.yaml`); en dCloud queda **desplegar, calibrar y medir**.

### 5.1 Habilitar el reparto de la GPU (time-slicing)

Hay UN solo L40S (48 GB) y queremos dos instancias de vLLM vivas a la vez (7B y
32B). Dos pods no pueden pedir una GPU entera cada uno, así que se expone el
L40S como varias "réplicas" con el device plugin de NVIDIA. Una sola vez:

```bash
cat >/tmp/time-slicing.yaml <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: time-slicing
  namespace: nvidia-device-plugin
data:
  any: |-
    version: v1
    sharing:
      timeSlicing:
        resources:
          - name: nvidia.com/gpu
            replicas: 4        # 1 GPU física -> 4 solicitables (nos bastan 2)
EOF
kubectl apply -f /tmp/time-slicing.yaml
# reconfigurar el plugin para que use el ConfigMap (según cómo se instaló:
# helm upgrade ... --set-json config.name=time-slicing, o editar el DaemonSet)
kubectl -n agentes get nodes -o json | grep nvidia.com/gpu   # debe verse 4, no 1
```

El reparto real de VRAM lo fija `--gpu-memory-utilization` en `vllm.yaml`
(local 0.22, grande 0.55): time-slicing solo permite que ambos pods *entren* en
el mismo L40S; no divide la memoria por sí solo.

### 5.2 Bajar pesos y desplegar vLLM

Qwen2.5 no es gated (a diferencia del guardrail): vLLM baja los pesos de Hugging
Face al arrancar, al PVC de cada instancia. El 32B AWQ (~19 GB) tarda.

```bash
kubectl apply -f deploy/k8s/vllm.yaml
kubectl -n agentes rollout status deploy/vllm-local  --timeout=10m
kubectl -n agentes rollout status deploy/vllm-grande --timeout=20m
kubectl -n agentes logs -f deploy/vllm-grande        # vigilar la carga de pesos
```

Si el 32B no arranca por VRAM, subir su `--gpu-memory-utilization` y bajar el
del 7B en `vllm.yaml`, y re-aplicar.

### 5.3 Apuntar los agentes a vLLM

En `deploy/k8s/endpoints.yaml`:

```yaml
LLM_BACKEND: "vllm"
LLM_LOCAL_URL:    "http://vllm-local:8000"
LLM_LOCAL_MODELO: "Qwen/Qwen2.5-7B-Instruct-FP8"
LLM_GRANDE_URL:    "http://vllm-grande:8000"
LLM_GRANDE_MODELO: "Qwen/Qwen2.5-32B-Instruct-AWQ"
```

```bash
kubectl apply -f deploy/k8s/endpoints.yaml
kubectl -n agentes rollout restart deploy      # las variables se leen al arrancar
```

`LLM_BACKEND=vllm` hace que `red.LLAMAR` use el cliente vLLM (salida estructurada
por `guided_json` en vez de `format` de Ollama) y que cada llamada mida el TTFT.

### 5.4 Calibrar las tres barras de caché (frío / tibio / caliente)

El TTFT sale de las métricas Prometheus de vLLM, no se estima
(`ttft_desde_prometheus` en `agents/llm_provider.py`). Para fijar los umbrales
de `UmbralesCache` (`agents/costos.py`):

1. Correr un caso con caché fría (recién arrancado) → TTFT alto = **frío**.
2. Repetir el mismo caso enseguida → prefill reusado en VRAM = **caliente**.
3. Con LMCache activo, tras desalojar de VRAM → lectura de NVMe = **tibio**.

```bash
kubectl -n agentes exec deploy/vllm-grande -- \
  sh -c 'curl -s localhost:8000/metrics | grep time_to_first_token'
```

Ajustar `caliente_max_ms` y `tibio_max_ms` a lo medido.

### 5.5 Contador de costo

Ya funciona: el Orquestador devuelve `costo` en cada corrida y la UI lo muestra
(Enriquecedor local en $0, los que debaten al precio de frontier). Ajustar la
tabla de precios que se mostrará en el evento en `endpoints.yaml`
(`PRECIO_GRANDE_ENTRADA`/`SALIDA`, etc.).

### 5.6 LMCache (offload a NVMe) — la barra "tibio", frágil

vLLM + LMCache es la pieza más quebradiza (CLAUDE.md §9). Está **desactivado por
defecto**: `vllm.yaml` corre con `--enable-prefix-caching` (reúso en VRAM, sin
disco), que da las barras caliente/frío sin riesgo. Para intentar la barra
"tibio", descomentar los bloques `LMCACHE_*` de `vllm.yaml`, montar el volumen
NVMe y validar que arranca. **Si falla, dejarlo apagado**: el resto de la Fase 4
no depende de LMCache.

## 6. Aplicar las políticas de seguridad y comprobar

```bash
kubectl apply -f deploy/k8s/politicas/estricta.yaml
kubectl apply -f deploy/k8s/politicas/tetragon-agentes-sin-exec.yaml
bash herramientas/probar_politica.sh         # matriz de la tabla de contratos
kubectl -n agentes exec deploy/ui -- python -m servicios.verificar
```

La UI se abre con un port-forward al `svc/ui` (puerto 8501), igual que en el
lab local (ver `GUIA_DEMO.md`).
