# Guía para operar la demo

Estado a 2026-09-15: Fases 1, 2 y 3 completas y validadas; Fase 5 (modo
presentación) en marcha. Falta la Fase 4 (inferencia y costo, requiere GPU de
dCloud). Esta guía cubre lo que ya funciona en el lab local.

## 1. Encender el entorno

Desde PowerShell en Windows:

```powershell
multipass start lab
```

Si tras un reinicio de la laptop los pods quedan en `Unknown` o
`ContainerCreating` (Cilium no conecta), repara el cluster con un comando:

```powershell
multipass exec lab -- bash ~/demo/lab/reparar-cluster.sh
```

Consulta la IP de la VM (cambia en cada arranque) y déjala a mano:

```powershell
multipass info lab
```

Levanta los accesos desde el navegador de Windows (dentro de la VM):

```powershell
multipass exec lab -- bash -c "for u in ui:agentes:ui:8501:8501 orquestador:agentes:orquestador:8000:8000 hubble:kube-system:hubble-ui:12000:80; do IFS=: read n ns svc lp rp <<< \"$u\"; sudo systemctl reset-failed pf-$n 2>/dev/null; sudo systemd-run --quiet --unit=pf-$n --uid=ubuntu --setenv=KUBECONFIG=/home/ubuntu/.kube/config /usr/local/bin/kubectl -n $ns port-forward --address 0.0.0.0 svc/$svc $lp:$rp; done"
```

Comprueba que todo responde (desde la UI, único pod que puede con la política):

```powershell
multipass exec lab -- kubectl -n agentes exec deploy/ui -- python -m servicios.verificar
```

- **UI:** `http://<IP-de-la-VM>:8501`
- **Hubble (tráfico entre pods):** `http://<IP-de-la-VM>:12000` → namespace `agentes`

## 2. Demo 1 — el equipo delibera (minuto 17)

En la UI: **Deliberación → modo "En vivo"**, elige un expediente limpio
(`aml-0042`) y pulsa **Deliberar**. En CPU tarda ~15 min; para el evento se
usa el checkpoint (sección 4) o la GPU de dCloud.

Qué señalar: el debate se lee en el bus, el contador de tokens sube, el salto
lateral Investigador→Defensor, y la disposición del Árbitro pendiente de humano.

## 3. Demo 2 — el mismo caso, envenenado (minuto 27)

Elige `aml-crudo` o `aml-ofuscado` y **Deliberar**. Aparece el panel **tres
capas de seguridad**:

- `aml-crudo`: **Contenido** DETUVO la inyección burda. Parece resuelto.
- `aml-ofuscado`: **Contenido** la DEJÓ PASAR, pero **Red** responde 403 y
  **Kernel** manda SIGKILL. Las reglas atrapan lo que el clasificador no.

La etiqueta "Guardrail abierto (sustituto de Cisco AI Defense)" está a la vista.

## 4. Modo presentación (stand, sin esperar 15 min)

**Deliberación → modo "Presentación (checkpoint)"**: elige un checkpoint
guardado (`data/corridas/`) y avanza con **Siguiente paso**. Cada paso trae un
subtítulo que lo explica sin narrador. Marca **Pantalla grande** para el stand.

El guion se prepara completo al cargar: si algo va a fallar, falla al preparar,
no frente a la audiencia.

## 5. Al terminar

```powershell
multipass stop lab
```

Libera la RAM de la VM. Las corridas viven en memoria y se pierden; las que
valga la pena conservar, guárdalas antes (ver `data/corridas/LEEME.md`).

## Notas

- Todo corre sin internet: el modelo (Ollama), el guardrail y los eventos de
  seguridad son locales.
- La VM de 10 GB corre el Demo 2 en vivo al límite de memoria (~148 MB libres),
  sin fallar. En dCloud sobra.
- Detalle honesto: en el Demo 2 las ACCIONES del ataque se bloquean, pero el
  TEXTO de la inyección alcanza a entrar al contexto del debate (mejora futura,
  ver `deploy/README.md`).
