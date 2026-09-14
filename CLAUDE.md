IMPORTANT:

Before you make any change, create and checkout a feature branch  named
"feature_some_short_name". Make and then commit your changes in this branch

# Proyecto: demo multi-agente para Cisco Connect LATAM

Contexto permanente del proyecto. Léelo completo antes de proponer cambios.
Si algo aquí contradice lo que parece razonable, gana este archivo: las
decisiones ya se tomaron con motivo.

---

## 1. Qué construimos

Una sesión técnica de 60 minutos en Cisco Connect LATAM, con dos bloques de
demo en vivo intercalados entre diapositivas, más presets para el stand de
demos.

**Tesis de la sesión:**

> Un agente suelto es un experimento. Varios agentes trabajando juntos son un
> sistema de producción, y como todo sistema de producción necesita controles de
> seguridad y de costo que no dependan de la buena voluntad del modelo.

**Audiencia:** arquitectos de IA y de IT. **No es una audiencia bancaria.** El
caso de uso es decorado que se explica en 30 segundos y no se vuelve a tocar.
Nada de marco regulatorio, tipologías ni umbrales.

**Los tres insights que la sala debe recordar:**

1. **Un agente no es un modelo.** Investigador y Defensor corren sobre los
   mismos pesos, en el mismo servidor. Lo que los hace agentes distintos es su
   prompt, su identidad y sus permisos.
2. **El costo de una malla vive en las aristas.** Cuatro agentes leyendo el
   mismo expediente lo prefillean cuatro veces, sin que nadie se equivoque. El
   impuesto de contexto se paga en cada handoff, salvo que compartas la caché.
3. **El ataque no rompe el perímetro, abusa de una arista que tú autorizaste.**
   Por eso la política tiene que ser sobre la intención del mensaje (capa 7), no
   solo sobre el par origen-destino (capa 4).

---

## 2. El caso de uso

Triage de alertas de monitoreo transaccional (AML). Lo único que hay que decir
en la sesión:

> Los bancos revisan transacciones sospechosas. Sus sistemas generan decenas de
> miles de alertas al mes y más del 90% son falsos positivos. Cada una la revisa
> una persona que junta contexto y escribe por qué esa operación tiene o no
> tiene sentido. Eso último, el escrito, es lo que le damos a un equipo de
> agentes.

**Límite que mantiene creíble la premisa:** el Árbitro nunca cierra un caso por
su cuenta. Decide, redacta la disposición recomendada y la registra. Un humano
confirma. El ataque es interesante precisamente porque no necesita vencer al
humano: le basta envenenar lo que el humano lee.

**El esquema debe ser neutral al dominio.** Habrá dos casos de reserva de triage
de alertas de SOC que usan el mismo esquema y los mismos agentes sin cambios de
código. Nunca uses vocabulario de AML en nombres de campos, clases o rutas
(nada de `cliente`, `monto`, `cuenta_origen`). Usa alerta, sujeto y evidencia.

---

## 3. Los cinco componentes

Cuatro agentes más un sistema de registro que **no es agente**: es donde vive la
capacidad peligrosa.

| Agente | Función |
|---|---|
| **Orquestador** | Conduce la deliberación, lleva el presupuesto de tokens. No opina. |
| **Enriquecedor** | Reúne y normaliza el contexto del sujeto. Único que ve datos del sujeto y único que ingiere texto externo. |
| **Investigador** | Argumenta que hay riesgo. |
| **Defensor** | Argumenta que hay explicación legítima. |
| **Árbitro** | Decide, redacta la disposición y la registra. |

### Matriz de permisos

Esta tabla es a la vez el slide de separación de poderes y la especificación de
las políticas de Cilium.

| | Ve datos del sujeto | Sale al modelo grande | Anexa al registro | Dispone del caso |
|---|---|---|---|---|
| Orquestador | no | no | sí | no |
| Enriquecedor | **sí** | no (usa el local) | sí | no |
| Investigador | no | sí | sí | no |
| Defensor | no | sí | sí | no |
| Árbitro | no | sí | sí | **sí** |

**Nadie tiene a la vez la primera y la última columna.** Ese es el diseño, y es
lo que el ataque intenta romper.

### Contratos HTTP

Son la especificación literal de la política de capa 7.

| Servicio | Ruta | Quién puede llamarla |
|---|---|---|
| enriquecedor | `POST /v1/enriquecer` | orquestador |
| investigador | `POST /v1/argumentar` | orquestador, defensor |
| defensor | `POST /v1/objetar` | orquestador, investigador |
| arbitro | `POST /v1/deliberar` | orquestador |
| registro | `POST /v1/anexar` | los cuatro agentes |
| registro | `POST /v1/disponer` | **solo arbitro** |

Las filas de investigador y defensor son el salto lateral: se llaman entre ellos
sin pasar por el orquestador. Eso es la malla de verdad y la política tiene que
permitirlo explícitamente.

Las dos últimas filas son todo el Demo 2. El Enriquecedor **sí tiene arista
legítima** hacia el registro (necesita anexar procedencia). El ataque usa esa
misma arista para llamar `/v1/disponer`: mismo origen, mismo destino, mismo
puerto, identidad verificada, tráfico cifrado. Todo lo que la capa 4 puede ver
está bien. Lo único que está mal es la ruta.

### Deliberación

Dos rondas fijas. Orquestador pide enriquecimiento → Investigador argumenta →
Defensor objeta → Investigador replica → Defensor cierra → Árbitro delibera y
dispone.

El Orquestador lleva un **presupuesto de tokens por caso**. Si se agota antes de
terminar, el Árbitro debe disponer con lo que hay y la disposición queda marcada
como emitida bajo presupuesto agotado. Esto convierte el costo de tablero de
observabilidad en **control de admisión**, y es el cierre de la sesión.

---

## 4. Esquema de caso

Neutral al dominio. El campo `source_trust` es el que hace todo el trabajo:
marca qué partes del contexto las escribió alguien de fuera.

```json
{
  "case_id": "aml-0042",
  "domain": "aml",
  "trigger": {
    "rule_id": "STRUCT-03",
    "rule_name": "Depósitos recurrentes bajo umbral",
    "fired_at": "2026-08-14T09:12:00Z",
    "severity": "media",
    "summary": "18 depósitos en efectivo bajo el umbral en 11 días"
  },
  "subject": {
    "id": "SUJ-88210",
    "display_name": "Refacciones Tepalca SA de CV",
    "declared_context": "Comercio de autopartes, ingresos esperados 40k-80k MXN/mes",
    "attributes": {}
  },
  "evidence": [
    {
      "id": "ev-001",
      "ts": "2026-08-03T11:04:00Z",
      "kind": "movimiento",
      "summary": "Depósito en efectivo 48,200 MXN",
      "free_text": "PAGO PROVEEDOR CONSIGNA AGO",
      "source_trust": "external",
      "attributes": {}
    }
  ],
  "history": [],
  "policy_excerpts": []
}
```

La inyección vive siempre en un `free_text` con `source_trust: "external"`. En
la UI, ese contenido debe renderizarse visualmente distinto. Del esquema sale
una estadística para el slide: qué porcentaje del contexto viene de fuentes no
controladas.

**Expedientes:** seis casos, ~35-40k tokens cada uno para que el impuesto de
contexto sea visible. Uno limpio, uno donde gana el Investigador, uno donde gana
el Defensor, uno con inyección burda, uno con inyección ofuscada, más dos de SOC
con el mismo esquema. Datos sintéticos, nombres claramente ficticios, etiqueta
"datos sintéticos" visible en pantalla siempre.

La inyección ofuscada debe pasar el guardrail **genuinamente**. Si el
clasificador la atrapa, hay que reescribirla, no debilitar el clasificador.

---

## 5. Los dos momentos de demo

Orden en la sesión (distinto al orden de construcción):

**Demo 1, minuto 17 (~5 min) — el equipo discute y el contador corre.**
Entra el caso. El Enriquecedor normaliza. Arranca el debate visible en pantalla:
Investigador argumenta, Defensor objeta citando política, Investigador replica.
El contador de tokens sube. La caché compartida evita que cada agente vuelva a
prefillear el expediente. El Árbitro dispone.

**Demo 2, minuto 27 (~6 min) — el mismo caso, envenenado.**
1. El guardrail atrapa la inyección burda. Parece resuelto.
2. La ofuscada pasa. El Enriquecedor obedece.
3. Intenta `POST /v1/disponer` → **403 de capa 7**. La arista era legítima, la
   petición no.
4. Intenta ejecutar un binario para lograrlo por otra vía → **SIGKILL**.

El paso 3 es el que prueba que la capa 4 no basta.

### Correlación entre lo que dice el agente y lo que vio el kernel

Las llamadas entre pods llevan `X-Trace-Id` y `X-Span-Id`. Con política L7
activa, Hubble ve esos headers y los dos carriles de la UI se alinean por trace,
no por ventana de tiempo.

**Consecuencia narrativa clave:** el intento de exfiltración no lleva trace_id
porque no nació del pipeline. Un flujo sin trace es algo que nadie pidió.

---

## 6. Punto de partida: qué existe

El repo viene de un demo previo de AGNTCY de originación de hipotecas. **La
estructura es correcta y se conserva. No reescribir la UI.**

```
app.py                    # entry point, CSS (rojo Cisco), ruteo por sidebar
agents/llm_provider.py    # abstracción multi-proveedor con salida JSON
agents/pipeline.py        # orquestación de 7 agentes (se reemplaza)
protocols/emitter.py      # ProtocolEmitter: SLIM, OTel spans, eventos DIR
data/scenarios.py         # escenarios de prueba
pages/_pipeline_view.py   # bus SLIM, cascada OTel, descubrimiento, bitácora
ml/models.py              # XGBoost y GNN (queda fuera de esta sesión)
```

**Se reutiliza tal cual:** `emitter.py`, `llm_provider.py`, `_pipeline_view.py`,
`app.py` y el CSS.

**Se reemplaza:** `pipeline.py`. Los siete agentes del demo de hipotecas
desaparecen; quedan los cinco componentes de la sección 3.

### Defectos conocidos del código previo que hay que corregir

1. **La malla era una estrella.** Todos los mensajes SLIM iban de `orchestrator`
   a un agente y de vuelta. El salto lateral investigador↔defensor lo arregla.
2. **Lo que se llamaba paralelo era secuencial.** `run_pipeline` corría los
   pasos "paralelos" uno tras otro y la cascada de OTel lo delataba. En esta
   versión el paralelismo debe ser real donde se anuncie.
3. **`identity_verified` estaba escrito a mano como `True`** en
   `emit_slim_message`, igual que `encryption: MLS` y `signature_alg: Ed25519`.
   No poner ese panel al frente hasta que venga de mTLS real.

---

## 7. Mapeo a Cisco Secure AI Factory

SAIF no es un producto: es una arquitectura validada (CVDs y CRAs) alineada a
las Reference Architectures de NVIDIA, con capas de cómputo, red, almacenamiento
y seguridad. Nuestro demo es un AI POD mínimo en el tier de inferencia
edge/enterprise, no una miniatura del data center.

| Nuestro componente | Producto real | En el lab |
|---|---|---|
| Capa de contenido | Cisco AI Defense | **NO disponible.** Guardrail abierto |
| Capa de red | Isovalent Enterprise Platform (Cilium) | Sí |
| Capa de kernel | Isovalent Enterprise Runtime Security (Tetragon) | Sí |
| Inferencia | vLLM en UCS con GPU | Sí (L40S en dCloud) |

### Reglas de honestidad, no negociables

- **Cilium NO inspecciona prompts.** Hace política L7 sobre HTTP (método, ruta,
  headers) y visibilidad de flujos. La detección de inyección es análisis de
  contenido y es otra capa. Nunca mezclar las dos.
- **Lo sustituido se dice en pantalla.** La capa de contenido lleva etiqueta
  visible: "Guardrail abierto (sustituto de Cisco AI Defense en este lab)".
- **No afirmar que algo está verificado si no lo está.**
- No inventar nombres de producto ni capacidades de Cisco.

---

## 8. Entorno

**Sin código de simulación.** Toda la inferencia y todos los eventos de
seguridad son reales. Ollama en CPU es inferencia real, no simulación, y es el
backend de desarrollo.

**Desarrollo local:** Windows con VM Ubuntu 24.04 vía Multipass (WSL2 no sirve:
su kernel no siempre expone BTF y Tetragon lo necesita). Dentro de la VM: kind
con Cilium (sin CNI por defecto, sin kube-proxy), Tetragon, y Ollama con un
modelo pequeño (qwen2.5:3b o similar). Todo el Demo 2 es desarrollable aquí.

Si la VM va lenta, se puede correr Ollama en el host Windows y apuntar los pods
a la IP del host.

**dCloud:** un L40S de 48 GB, **disponible solo en reservas cortas**. Esto es
una restricción de diseño: todo lo que pueda desarrollarse sin GPU debe
desarrollarse sin GPU. Las sesiones de dCloud se reservan para vLLM, jerarquía
de caché y mediciones de costo.

Plan de modelos en el L40S: un 7B en FP8 (~8 GB) para el Enriquecedor, y un 32B
cuantizado a 4 bits (~19 GB) para Investigador, Defensor y Árbitro. Quedan ~20
GB para caché, que es lo que hace visible la presión de memoria. El 32B hace el
papel de "frontier" con el precio real de un modelo frontier asignado, pero
corre local para no depender de la red del recinto. Decirlo en pantalla.

**Nada depende de internet el día del evento.**

**Reconstrucción:** `lab/bootstrap.sh` es el artefacto portable. La VM es
desechable. Todo cambio de entorno se escribe ahí, nunca solo se teclea.

---

## 9. Fases de construcción

Orden por dependencia, no por orden de la sesión. No saltar fases.

### Fase 1 — Los cinco componentes hablándose

- Servicio HTTP mínimo (FastAPI) por cada componente, con los contratos de la
  sección 3. Una imagen, un Deployment y un Service por cada uno.
- Orquestador que conduce las dos rondas y lleva el presupuesto.
- Prompts de Investigador, Defensor y Árbitro. **Aquí vive la calidad del demo:**
  el debate tiene que leerse bien proyectado, con argumentos concretos que citen
  evidencia y política, no generalidades.
- Esquemas `ArgumentoV1` y `ObjecionV1`: son lo que la sala lee en el bus SLIM.
- Backend Ollama en `llm_provider.py`.
- Dos expedientes de prueba.

**Aceptación:** el debate completo corre sobre pods en kind, con Ollama, y se
lee en la UI.

### Fase 2 — Instrumentación y dos carriles

- `security_events` como **cuarta lista separada** en `ProtocolEmitter`, sin
  mezclar con las tres existentes, para no romper las vistas actuales.
  `emit_security_event(ctx, layer, source, action, verdict, detail, trace_id)`
  con `layer` en `content|cilium|tetragon` y `verdict` en
  `FORWARDED|DROPPED|SIGKILL|HTTP_403`.
- Propagación de `X-Trace-Id` y `X-Span-Id` entre pods.
- `protocols/kernel_watch.py`: lee `hubble observe -o json`, extrae el trace del
  header, alimenta `emit_security_event`.
- Panel nuevo en `_pipeline_view.py`: dos carriles en el mismo eje de tiempo.
  Izquierda el envelope SLIM (lo que el agente dice), derecha el evento
  observado (lo que el kernel vio). Un flujo sin contraparte a la izquierda es
  la señal de alarma.

**Aceptación:** los dos carriles coinciden en un caso limpio.

### Fase 3 — Las tres capas y el Demo 2

- Guardrail de contenido con clasificador real (no regex), corriendo aparte.
- `CiliumNetworkPolicy` L3/L4 y L7 derivadas de las tablas de la sección 3.
- `TracingPolicy` de Tetragon con `matchActions: Sigkill`.
- Watcher de Tetragon en `kernel_watch.py`.
- Los dos expedientes envenenados.

**Aceptación:** la secuencia de cuatro pasos del Demo 2, con eventos reales.

### Fase 4 — Inferencia y costo (requiere dCloud)

- Backend vLLM en `llm_provider.py`, dos instancias.
- Jerarquía de caché con offload a NVMe. Medir TTFT desde métricas Prometheus de
  vLLM, **no estimar**.
- Tres barras, no dos: frío, tibio (disco), caliente (VRAM).
- Contador de costos con tabla de precios configurable, y el presupuesto
  aplicado de verdad.

**Nota de fragilidad:** vLLM + LMCache es la pieza más quebradiza del proyecto.
Fijar versiones exactas, congelar la imagen, no actualizar antes del evento.
Plan B: `--enable-prefix-caching` conserva el efecto sin el offload a disco.

**Aceptación:** el Demo 1 con números reales.

### Fase 5 — Modo presentación

- Paso a paso: el guion se ejecuta completo al preparar y los eventos se revelan
  de uno en uno con un botón. **Si algo falla, debe fallar al preparar, no a
  media narración frente a la audiencia.**
- Checkpoints serializados por demo, para que cada una arranque
  independientemente aunque la anterior no haya corrido.
- Presets del stand: bucle de atracción (~50s), guiado corto (solo Demo 2,
  ~4 min), profundo (ambos, ~11 min).
- Rotación de expedientes para que la caché fría funcione con cada visitante.
- Tipografía legible a 4 metros. Subtítulos que expliquen cada paso sin
  narrador: un colega va a operar el stand.

---

## 10. Cómo trabajar en este repo

- El usuario sabe poco de Kubernetes y está aprendiendo en el proceso. **Explica
  qué haces y por qué, en español, con comentarios en el código.** No entregues
  código sin contexto.
- Cambios pequeños y verificables sobre refactors grandes. Antes de cambiar algo
  existente, explica qué hace hoy.
- Antes de agregar dependencias, pregunta.
- No reescribir `_pipeline_view.py` ni el CSS desde cero. Se extienden.
- Commits pequeños y frecuentes, en español, describiendo qué funciona ahora que
  antes no.
- Todo lo que haya que instalar en el entorno va a `lab/bootstrap.sh`.

### No objetivos

- No hay modo simulación. Si algo no se puede probar de verdad, se deja
  pendiente, no se finge.
- No rehacer `lab/` (bootstrap, cluster kind, políticas base): ya funciona.
- Los modelos de XGBoost y GNN del demo previo quedan fuera de esta sesión.
- Las diapositivas se arman aparte.

---

## 11. Decisiones abiertas

Marcadas para confirmación del usuario:

- **Orquestador separado del Árbitro.** Se eligió separarlos para no contaminar
  la separación de poderes.
- **El presupuesto lo lleva el Orquestador y el Árbitro lo respeta.**
