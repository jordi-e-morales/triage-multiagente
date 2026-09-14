# Imagen única para los seis componentes de la demo.
#
# Cada Deployment la usa con una variable distinta:
#   COMPONENTE=orquestador | enriquecedor | investigador | defensor | arbitro | registro
# y arranca `uvicorn servicios.<COMPONENTE>:app` en el puerto 8000.
#
# Construir y cargar en kind (dentro de la VM):
#   docker build -t triage-agentes:0.2.0 .
#   kind load docker-image triage-agentes:0.2.0 --name agentes --nodes agentes-worker

# Fijada por digest (amd64, publicada 2026-09-02): la imagen del evento debe ser
# exactamente la que se ensayó, aunque el tag 3.13-slim se actualice.
FROM python:3.13-slim@sha256:cc9dffa47c8294ba9bb795a8dfaeb7b76f2b30acade2c52a461a2999d127eb00

# Sin archivos .pyc (el sistema de archivos del contenedor será de solo
# lectura) y salida sin búfer para que `kubectl logs` muestre todo al momento.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-servicios.txt .
RUN pip install --no-cache-dir -r requirements-servicios.txt

# Solo el código que corre en los pods. La UI (pages/, app.py), el demo previo
# (agents/pipeline.py, ml/) y las pruebas no entran a la imagen.
COPY agents/__init__.py agents/llm_provider.py agents/triage.py agents/
COPY schemas/ schemas/
COPY servicios/ servicios/

# Usuario sin privilegios. Menos permisos dentro del contenedor = menos que
# pueda hacer un agente comprometido (y más fácil de vigilar con Tetragon).
RUN useradd --uid 10001 --no-create-home agente
USER 10001

ENV COMPONENTE=registro
EXPOSE 8000
# `exec` para que uvicorn sea el proceso 1 y reciba las señales de Kubernetes.
CMD ["sh", "-c", "exec uvicorn servicios.${COMPONENTE}:app --host 0.0.0.0 --port 8000"]
