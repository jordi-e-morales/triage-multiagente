# Puesta en marcha en dCloud

Pasos para levantar la demo en el servidor de dCloud (L40S) desde cero,
clonando de GitHub. Todo corre dentro de dCloud; la laptop solo abre el
navegador.

## 1. Clonar los dos repos

```bash
git clone https://github.com/jordi-e-morales/connect26-demo.git
git clone https://github.com/jordi-e-morales/agntcy-mortgage-demo-python.git
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
GitHub. Descárgalo con tu cuenta (una vez) y déjalo en `./modelo`:

```bash
pip install -U "huggingface_hub[cli]"
huggingface-cli login          # pega tu token de Hugging Face
huggingface-cli download meta-llama/Llama-Prompt-Guard-2-22M \
  --local-dir agntcy-mortgage-demo-python/modelo
```

(Requiere aceptar la licencia en huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M.)

## 4. Construir imágenes y desplegar (repo agntcy-mortgage-demo-python)

```bash
cd agntcy-mortgage-demo-python
docker build -t triage-agentes:0.6.0 .
docker build -f Dockerfile.ui -t triage-ui:0.6.0 .
docker build -f Dockerfile.guardrail -t triage-guardrail:0.5.0 .   # usa ./modelo
kind load docker-image triage-agentes:0.6.0 triage-ui:0.6.0 triage-guardrail:0.5.0 \
  --name agentes --nodes agentes-worker

kubectl apply -f deploy/k8s/                 # namespace, endpoints, agentes, ui, ollama, observador
kubectl apply -f deploy/k8s/guardrail.yaml
```

## 5. Modelo de lenguaje: aquí sí hay GPU (Fase 4)

En el lab local se usa Ollama en CPU (`deploy/k8s/ollama.yaml`). En dCloud, la
Fase 4 sustituye eso por vLLM en la L40S:

- Dos instancias: un 7B (Enriquecedor) y un 32B cuantizado (Investigador,
  Defensor, Árbitro), esta última como "frontier" con precio real pero local.
- Editar en `deploy/k8s/endpoints.yaml` `LLM_LOCAL_*` y `LLM_GRANDE_*` para
  apuntar a vLLM, y reiniciar los pods (`kubectl -n agentes rollout restart deploy`).
- Medir TTFT desde las métricas Prometheus de vLLM (frío / tibio en disco /
  caliente en VRAM) — no estimar.

Esta parte (vLLM, jerarquía de caché, contador de costo) es el trabajo que
queda por construir en la reserva de dCloud.

## 6. Aplicar las políticas de seguridad y comprobar

```bash
kubectl apply -f deploy/k8s/politicas/estricta.yaml
kubectl apply -f deploy/k8s/politicas/tetragon-agentes-sin-exec.yaml
bash herramientas/probar_politica.sh         # matriz de la tabla de contratos
kubectl -n agentes exec deploy/ui -- python -m servicios.verificar
```

La UI se abre con un port-forward al `svc/ui` (puerto 8501), igual que en el
lab local (ver `GUIA_DEMO.md`).
