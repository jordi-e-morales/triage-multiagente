# Multi-agentes bajo control

Demo para Cisco Connect LATAM: un equipo de agentes que delibera sobre una
alerta y los controles de **seguridad** y **costo** que lo contienen. La tesis:

> Un agente suelto es un experimento. Varios agentes trabajando juntos son un
> sistema de producción, y como todo sistema de producción necesita controles
> que no dependan de la buena voluntad del modelo.

Cada componente corre en su propio pod de Kubernetes. Esa frontera es lo que
hace posibles los controles: hay tráfico que inspeccionar, identidad que
verificar y procesos que vigilar.

## El caso de uso

Triage de alertas de monitoreo (AML/SOC). Un equipo de agentes reúne el
contexto de una alerta, debate si escalarla y registra una disposición que un
humano confirma. El esquema es neutral al dominio (alerta, sujeto, evidencia).

## Los cinco componentes

| Componente | Función |
|---|---|
| **Orquestador** | Conduce la deliberación y lleva el presupuesto de tokens. |
| **Enriquecedor** | Reúne el contexto del sujeto. Único que ve datos del sujeto y que ingiere texto externo. |
| **Investigador** | Argumenta que hay riesgo. |
| **Defensor** | Argumenta que hay explicación legítima. |
| **Árbitro** | Decide, redacta la disposición y la registra. |

Más un **Registro** (no es agente: es donde vive la capacidad peligrosa) y un
**Guardrail** de contenido.

## Las dos demos

- **Demo 1 — el equipo delibera.** Entra la alerta, el Enriquecedor normaliza,
  el Investigador y el Defensor debaten (con un salto lateral directo entre
  ellos), el contador de tokens sube y el Árbitro dispone.
- **Demo 2 — el mismo caso, envenenado.** Un documento externo esconde una
  inyección. Tres capas responden:
  - **Contenido** (guardrail): atrapa la inyección burda; la ofuscada la deja
    pasar —a propósito: un clasificador adivina intenciones y algún día falla—.
  - **Red** (Cilium, capa 7): responde 403 cuando el agente intenta una ruta
    que no le toca.
  - **Kernel** (Tetragon): mata con SIGKILL si intenta ejecutar un binario.

## Cómo correrlo

- Operar la demo en el lab local: **[GUIA_DEMO.md](GUIA_DEMO.md)**.
- Levantar en dCloud (con GPU): **[DCLOUD.md](DCLOUD.md)**.
- Manifiestos de Kubernetes y detalles de despliegue: **[deploy/README.md](deploy/README.md)**.
- El entorno (VM, kind, Cilium, Tetragon) vive en el repo
  [connect26-demo](https://github.com/jordi-e-morales/connect26-demo).

Toda la inferencia y todos los eventos de seguridad son reales: no hay modo
simulación. En desarrollo, el modelo corre en Ollama (CPU); en dCloud, en vLLM
sobre GPU.

## Estructura

```
app.py                 UI (Streamlit): Deliberación, Admin
pages/                 vistas de la UI (deliberación, panel de dos carriles, Demo 2)
servicios/             un servicio HTTP (FastAPI) por componente + guardrail + observador
agents/                lógica de los agentes (triage) y del Demo 2
schemas/               esquema de caso y mensajes de deliberación (Pydantic)
protocols/             emisor de eventos y lector de Hubble/Tetragon
deploy/k8s/            manifiestos y políticas de Cilium/Tetragon
data/casos/            expedientes sintéticos (incluye los envenenados)
data/corridas/         checkpoints guardados para el modo presentación
tests/                 pruebas (unittest); se corren con: python -m unittest discover -s tests -t .
```

## Estado

- **Fases 1, 2, 3 completas y validadas en cluster:** los cinco componentes
  hablándose, el panel de dos carriles (lo que dicen los agentes vs. lo que vio
  la red, alineado por traza) y las tres capas de seguridad del Demo 2.
- **Fase 5 (modo presentación):** reproducción de checkpoints paso a paso, con
  subtítulos y modo pantalla grande para el stand.
- **Fase 4 (inferencia y costo):** pendiente; requiere la GPU de dCloud.

## Origen

Partió del demo abierto de AGNTCY de originación de hipotecas (de ahí parte de
la estructura de la UI y el emisor de protocolos); el pipeline y el caso de uso
se reescribieron para esta sesión.

Datos sintéticos, nombres ficticios.
