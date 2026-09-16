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
se sustituye por vLLM en la L40S. El código ya está (backend vLLM en
`agents/llm_provider.py`, contador de costo en `agents/costos.py`); en dCloud
queda **desplegar, calibrar y medir**.

**vLLM corre en el HOST, no en pods.** Meter la GPU dentro de kind (device
plugin + time-slicing) es la pieza más frágil del proyecto; en cambio, correr
vLLM en el host y apuntar los pods a la IP del host es lo que el propio
CLAUDE.md §8 ya permite (igual que Ollama en el host en desarrollo). Los agentes
no se enteran: siguen llamando a `http://vllm-local:8000` y
`http://vllm-grande:8000`, que son Services que redirigen al host.

Requisito: el host debe ver la GPU (`nvidia-smi` responde) y tener el **NVIDIA
Container Toolkit** para que `docker run --gpus all` funcione. Comprobar:

```bash
nvidia-smi                                   # la L40S debe aparecer
# Docker ve la GPU (la imagen de vLLM arranca sola, por eso --entrypoint):
docker run --rm --gpus all --entrypoint nvidia-smi vllm/vllm-openai:v0.6.6.post1
```

Si el segundo falla, instalar el toolkit (una vez, va a `lab/bootstrap.sh`):

```bash
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### 5.1 Levantar las dos instancias de vLLM en el host

Un solo script hace todo: arranca los dos contenedores repartiendo el L40S
(7B en `:18001`, 32B en `:18000`), espera a que respondan, calcula la IP del
host para el cluster y crea los Services `vllm-local` / `vllm-grande`.

```bash
bash deploy/vllm-host/vllm-up.sh
```

Qwen2.5 no es gated (a diferencia del guardrail): vLLM baja los pesos de Hugging
Face al arrancar, a `~/.cache/huggingface` (se conserva entre reinicios del
contenedor; se re-baja tras una reconstrucción del lab). El 32B AWQ (~19 GB)
tarda varios minutos la primera vez. Vigilar con `docker logs -f vllm-grande`.

El reparto de VRAM lo fijan las fracciones (`0.28` local, `0.60` grande; suman
0.88, ~5.5 GB de colchón). El 32B, por sus pesos + grafos CUDA, necesita la
fracción mayor (con `0.52` se quedaba ~3.3 GB corto). Si aún no arranca: subir
`VLLM_FRAC_GRANDE`, bajar `VLLM_CTX_GRANDE`, o añadir `--enforce-eager` al 32B
(ahorra ~2-3 GB de grafos CUDA, a costa de algo de velocidad).

**Ventana de contexto:** los expedientes son de ~35-40k tokens y el Enriquecedor
ve el expediente completo, así que el modelo local abre `49152` con YaRN (Qwen2.5
es 32k nativo). Los que debaten reciben el caso recortado y les basta `32768`.
Es el otro punto a calibrar: si el local hace OOM, bajar `VLLM_CTX_LOCAL` (y/o
subir `VLLM_FRAC_LOCAL`); si los expedientes acaban siendo ≤32k, apagar YaRN con
`VLLM_ROPE_LOCAL=""` para no perder calidad en contextos cortos.

Apagar todo: `bash deploy/vllm-host/vllm-down.sh`.

### 5.2 Apuntar los agentes a vLLM

En `deploy/k8s/endpoints.yaml`:

```yaml
LLM_BACKEND: "vllm"
LLM_LOCAL_URL:    "http://vllm-local:8000"
LLM_LOCAL_MODELO: "Qwen/Qwen2.5-7B-Instruct"
LLM_GRANDE_URL:    "http://vllm-grande:8000"
LLM_GRANDE_MODELO: "Qwen/Qwen2.5-32B-Instruct-AWQ"
```

```bash
kubectl apply -f deploy/k8s/endpoints.yaml
kubectl -n agentes rollout restart deploy      # las variables se leen al arrancar
```

`LLM_BACKEND=vllm` hace que `red.LLAMAR` use el cliente vLLM (salida estructurada
por `guided_json` en vez de `format` de Ollama) y que cada llamada mida el TTFT.

### 5.3 Permitir (y acotar) el egress a los modelos

vLLM en el host obliga a reexpresar la separación de la matriz de permisos por
**puerto del host**: el Enriquecedor solo puede abrir el 18001 (local), los que
debaten solo el 18000 (grande).

```bash
kubectl apply -f deploy/k8s/politicas/vllm-host-egress.yaml
```

Se aplica ADEMÁS de `estricta.yaml`. Si el modelo no responde pero un `curl`
directo al host sí, ver la nota de clasificación `host`/`world` dentro del
archivo (cambiar `toEntities: [host]` por el CIDR que imprime `vllm-up.sh`).

### 5.4 Calibrar las tres barras de caché (frío / tibio / caliente)

El TTFT sale de las métricas Prometheus de vLLM, no se estima
(`ttft_desde_prometheus` en `agents/llm_provider.py`). Para fijar los umbrales
de `UmbralesCache` (`agents/costos.py`):

1. Correr un caso con caché fría (recién arrancado) → TTFT alto = **frío**.
2. Repetir el mismo caso enseguida → prefill reusado en VRAM = **caliente**.
3. Con LMCache activo, tras desalojar de VRAM → lectura de NVMe = **tibio**.

```bash
curl -s http://127.0.0.1:18000/metrics | grep time_to_first_token   # 32B, en el host
```

Ajustar `caliente_max_ms` y `tibio_max_ms` a lo medido.

### 5.5 Contador de costo

Ya funciona: el Orquestador devuelve `costo` en cada corrida y la UI lo muestra
(Enriquecedor local en $0, los que debaten al precio de frontier). Ajustar la
tabla de precios que se mostrará en el evento en `endpoints.yaml`
(`PRECIO_GRANDE_ENTRADA`/`SALIDA`, etc.).

### 5.6 LMCache (offload a NVMe) — la barra "tibio", frágil

vLLM + LMCache es la pieza más quebradiza (CLAUDE.md §9). Está **desactivado por
defecto**: `vllm-up.sh` arranca con `--enable-prefix-caching` (reúso en VRAM, sin
disco), que da las barras caliente/frío sin riesgo. Para intentar la barra
"tibio", agregar la configuración de LMCache al `docker run` (variables
`LMCACHE_*` y un volumen en NVMe) y validar que arranca. **Si falla, dejarlo
apagado**: el resto de la Fase 4 no depende de LMCache.

## 6. Aplicar las políticas de seguridad y comprobar

```bash
kubectl apply -f deploy/k8s/politicas/estricta.yaml
kubectl apply -f deploy/k8s/politicas/tetragon-agentes-sin-exec.yaml
bash herramientas/probar_politica.sh         # matriz de la tabla de contratos
kubectl -n agentes exec deploy/ui -- python -m servicios.verificar
```

La UI se abre con un port-forward al `svc/ui` (puerto 8501), igual que en el
lab local (ver `GUIA_DEMO.md`).
