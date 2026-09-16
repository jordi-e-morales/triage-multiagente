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

Los dos modelos van en **AWQ** (4 bits). El local se cambió de FP8 a AWQ porque
el FP8 dinámico obliga a cargar el bf16 (~15 GB) y comprimir, y ese pico no cabe
al compartir GPU con el 32B; AWQ carga ya cuantizado (~5.5 GB), sin pico.

**Sin sacrificar ventana de contexto** (es el tema de la sesión): la caché KV va
en **fp8** por defecto (mitad de memoria), lo que permite local 32k + grande 16k
en el L40S. Huella medida: ~13 GB local + ~22 GB grande = ~35 GB de 46.

Cómo arranca (todo en `vllm-up.sh`, no se teclea):
- **Secuencial**, no en paralelo: primero el local, se espera a que cargue, y
  solo entonces el grande. Si arrancan a la vez se pisan la memoria al perfilar
  la caché y fallan de forma errática.
- Fracciones `0.30` local, `0.68` grande. vLLM **NO cuenta la memoria del otro
  modelo**: cada instancia llena su presupuesto `util × 44.43` para sí misma, así
  que los dos deben caber físicamente: `uso_local + uso_grande ≤ 44.43`. Medido:
  el local con 0.30 usa ~8.5 GB; al grande le quedan ~36 GB → su fracción ≤ 0.80,
  y 0.68 (~30 GB) deja colchón. **Si el grande hace OOM, BAJAR su fracción, no
  subirla.**
- El 32B corre con `--enforce-eager` y ambos con
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` (evita OOM por fragmentación).

**No caben si la GPU no está limpia:** un proceso viejo aparece como `non_torch`
y desplaza todo. `vllm-up.sh` barre ambos contenedores al inicio; aun así, si ves
`non_torch` inesperadamente alto, revisa `nvidia-smi` (debe estar ~1 MiB antes).

**Antes de arrancar, la GPU debe estar casi vacía** (`nvidia-smi` ~1 MiB). Si un
proceso viejo ocupa VRAM aparece en el log como `non_torch_memory` y deja la KV
en negativo — nada arranca. Límpialo con `vllm-down.sh` o `kill -9` del PID.

Si el 32B da "No available memory for the cache blocks" con la GPU limpia:
`VLLM_EAGER_GRANDE=1` (quita grafos CUDA, ~2-3 GB), bajar `VLLM_CTX_GRANDE`, o
`VLLM_KV_DTYPE=fp8`.

**Ventana de contexto:** por defecto el local abre `32768` (el Enriquecedor ve el
expediente completo) y el grande `16384` (los que debaten reciben el recortado).
OJO: las ventanas COMPITEN por la VRAM (vLLM reserva activaciones proporcionales
a max-model-len al perfilar la caché); medido en dCloud, `32768` en AMBOS no cabe
en el L40S (el pico de activaciones del 32B a 32k no deja caché para los dos).

Los expedientes de diseño son de ~35-40k y el Enriquecedor ve el expediente
completo, así que para darle esa ventana hay que HACER SITIO, no solo subir la
ventana. Receta (calibración, cuando existan los expedientes de 40k):

```bash
VLLM_CTX_LOCAL=49152 VLLM_KV_DTYPE=fp8 VLLM_CTX_GRANDE=24576 \
VLLM_ROPE_LOCAL='{"rope_type":"yarn","factor":2.0,"original_max_position_embeddings":32768}' \
bash deploy/vllm-host/vllm-up.sh
```

(caché KV en fp8 = la mitad; bajar la ventana del grande le cede memoria al 7B).

Apagar todo: `bash deploy/vllm-host/vllm-down.sh`.

### 5.2 Apuntar los agentes a vLLM

En `deploy/k8s/endpoints.yaml`:

```yaml
LLM_BACKEND: "vllm"
# TEMPORAL: el 7B lo hace el 32B también. El checkpoint Qwen2.5-7B-Instruct-AWQ
# salió ROTO (genera basura a nivel de carácter, con cualquier backend), y el
# GPTQ-Int8 no cargó. Hasta tener un 7B que funcione, el 32B hace de "local".
# Se pierde solo la separación de costo local($0)/frontier del contador; el resto
# del demo queda igual. Para restaurar dos modelos: LLM_LOCAL_* de vuelta a
# vllm-local:8000 + un 7B que cargue limpio (probar GPTQ-Int4 o re-descargar).
LLM_LOCAL_URL:    "http://vllm-grande:8000"
LLM_LOCAL_MODELO: "Qwen/Qwen2.5-32B-Instruct-AWQ"
LLM_GRANDE_URL:    "http://vllm-grande:8000"
LLM_GRANDE_MODELO: "Qwen/Qwen2.5-32B-Instruct-AWQ"
```

El backend de guided decoding es **xgrammar** por defecto (`VLLM_GUIDED_BACKEND`):
el de vLLM por defecto (outlines) se atora con espacios en blanco infinitos y
desborda los tokens. Sin esto, NINGÚN agente produce JSON válido.

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

> ⚠️ **Orden obligatorio: primero `estricta.yaml`, luego el egress de modelos.**
> Al aplicar una política con `egress`, Cilium pone al pod en **egress
> default-deny** y solo deja salir lo que el CONJUNTO de políticas permita. El
> egress de modelos NO trae regla de DNS; el DNS lo habilita `base-dns`, que vive
> en `estricta.yaml`. Si aplicas el egress de modelos sin `estricta.yaml`, el pod
> se queda **sin DNS** ("Temporary failure in name resolution") y no resuelve ni
> `registro` ni `vllm-local`.

```bash
kubectl apply -f deploy/k8s/politicas/estricta.yaml   # trae base-dns (DNS)
bash deploy/vllm-host/egress-up.sh                    # egress a los modelos (CIDR real)
```

`egress-up.sh` acota por **puerto del host** (enriquecedor→18001 local,
debatientes→18000 grande) usando `toCIDRSet` con la IP real de la gateway de
kind. Se usa CIDR y no `toEntities: [host]` porque, medido en dCloud, Cilium en
kind NO clasifica esa gateway como la entidad `host`, y con `[host]` el egress
queda en TIMEOUT. El script verifica que `base-dns` esté antes y calcula la IP
(cambia en cada reconstrucción).

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
