"""
Catálogo único de endpoints: a dónde apunta cada componente y cada modelo.

Todo sale de variables de entorno. En Kubernetes esas variables vienen de un
ConfigMap (deploy/k8s/endpoints.yaml) que los Deployments cargan con
`envFrom`. Cambiar un apunte en dCloud es:

    1. editar deploy/k8s/endpoints.yaml
    2. kubectl apply -f deploy/k8s/endpoints.yaml
    3. kubectl -n agentes rollout restart deploy   (las variables se leen al arrancar)

La página Admin de la UI muestra estos valores y prueba la conectividad, pero
NO los modifica. Poder redirigir a qué modelo habla un agente es una capacidad
peligrosa (permite desviar tráfico), así que no la damos a ningún proceso del
cluster: la ejerce una persona con kubectl.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Servicio:
    nombre: str
    variable: str   # variable de entorno de la que sale la URL
    url: str


@dataclass(frozen=True)
class Modelo:
    rol: str        # "local" o "grande"
    usado_por: str
    variable_url: str
    url: str
    variable_modelo: str
    modelo: str
    # Ventana de contexto que se pide en cada llamada. Una sola variable para
    # los dos modelos: en desarrollo es el mismo modelo.
    num_ctx: int = 8192


# Nombres de Service de Kubernetes dentro del namespace. Por defecto todos
# escuchan en el 8000; así el valor por omisión sirve tal cual en el cluster.
_SERVICIOS = [
    ("orquestador", "URL_ORQUESTADOR", "http://orquestador:8000"),
    ("enriquecedor", "URL_ENRIQUECEDOR", "http://enriquecedor:8000"),
    ("investigador", "URL_INVESTIGADOR", "http://investigador:8000"),
    ("defensor", "URL_DEFENSOR", "http://defensor:8000"),
    ("arbitro", "URL_ARBITRO", "http://arbitro:8000"),
    ("registro", "URL_REGISTRO", "http://registro:8000"),
    # No es agente: sirve los eventos que observó la red (carril derecho).
    ("observador", "URL_OBSERVADOR", "http://observador:8000"),
    # Capa de contenido (sustituto de Cisco AI Defense). No es agente.
    ("guardrail", "URL_GUARDRAIL", "http://guardrail:8000"),
]


def servicios() -> list[Servicio]:
    return [Servicio(n, v, os.getenv(v, d)) for n, v, d in _SERVICIOS]


def url_de(nombre: str) -> str:
    """URL de un componente por nombre, p.ej. url_de('registro')."""
    for s in servicios():
        if s.nombre == nombre:
            return s.url
    raise KeyError(nombre)


def modelos() -> list[Modelo]:
    """
    Dos modelos, como en la matriz de permisos:
    - "local": solo el Enriquecedor, que es el único que ve datos del sujeto.
    - "grande": Investigador, Defensor y Árbitro.

    En desarrollo ambos pueden apuntar al mismo Ollama y al mismo modelo
    pequeño. En dCloud serán dos servidores distintos (7B y 32B), y separarlos
    por URL es lo que permite que Cilium impida al Enriquecedor llegar al
    grande.
    """
    num_ctx = int(os.getenv("LLM_NUM_CTX", "8192"))
    return [
        Modelo("local", "enriquecedor",
               "LLM_LOCAL_URL", os.getenv("LLM_LOCAL_URL", "http://ollama:11434"),
               "LLM_LOCAL_MODELO", os.getenv("LLM_LOCAL_MODELO", "qwen2.5:7b"), num_ctx),
        Modelo("grande", "investigador, defensor, arbitro",
               "LLM_GRANDE_URL", os.getenv("LLM_GRANDE_URL", "http://ollama:11434"),
               "LLM_GRANDE_MODELO", os.getenv("LLM_GRANDE_MODELO", "qwen2.5:7b"), num_ctx),
    ]


def modelo(rol: str) -> Modelo:
    """modelo('local') o modelo('grande')."""
    return next(m for m in modelos() if m.rol == rol)


def backend() -> str:
    """Backend de inferencia: 'ollama' (CPU, desarrollo) o 'vllm' (GPU, dCloud)."""
    return os.getenv("LLM_BACKEND", "ollama")


def precios() -> dict:
    """
    Precios por 1,000,000 de tokens (USD), por rol. El local es 0 por omisión
    (costo marginal ~cero); el grande lleva precio de frontier. Configurable con
    PRECIO_LOCAL_ENTRADA/SALIDA y PRECIO_GRANDE_ENTRADA/SALIDA.
    """
    from agents.costos import Precio
    return {
        "local": Precio(float(os.getenv("PRECIO_LOCAL_ENTRADA", "0")),
                        float(os.getenv("PRECIO_LOCAL_SALIDA", "0"))),
        "grande": Precio(float(os.getenv("PRECIO_GRANDE_ENTRADA", "0.60")),
                         float(os.getenv("PRECIO_GRANDE_SALIDA", "2.40"))),
    }


def presupuesto_tokens_caso() -> int:
    """
    Tokens (prompt + respuesta) que el Orquestador permite gastar por caso.

    Referencia medida: el debate completo de aml-0042 con qwen2.5:7b consumió
    ~15.8k tokens. 30k deja margen para una deliberación completa; bajarlo
    muestra el control de admisión en acción.
    """
    return int(os.getenv("PRESUPUESTO_TOKENS_CASO", "30000"))


def url_ai_defense() -> str:
    """
    URL base del gateway de Cisco AI Defense (incluye tenant y connection, hasta
    /v1). Vacío = capa de contenido real DESHABILITADA (el demo corre offline con
    solo el guardrail abierto). Es tenant-específica: va en env/ConfigMap, NO se
    commitea al repo.
    """
    return os.getenv("URL_AI_DEFENSE", "").strip()


def ai_defense_modelo() -> str:
    return os.getenv("AI_DEFENSE_MODELO", "gpt-4o-mini")


def ai_defense_habilitado() -> bool:
    """Se muestra el showcase de AI Defense solo si hay URL y API key."""
    return bool(url_ai_defense() and os.getenv("OPENAI_API_KEY", "").strip())


def admin_visible() -> bool:
    """En el stand se oculta la página Admin con MOSTRAR_ADMIN=0."""
    return os.getenv("MOSTRAR_ADMIN", "1") != "0"
