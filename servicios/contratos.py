"""
Cuerpos de las peticiones entre componentes (sección 3 de CLAUDE.md).

    enriquecedor  POST /v1/enriquecer  <- orquestador
    investigador  POST /v1/argumentar  <- orquestador, defensor
    defensor      POST /v1/objetar     <- orquestador, investigador
    arbitro       POST /v1/deliberar   <- orquestador
    registro      POST /v1/anexar      <- los cuatro agentes
    registro      POST /v1/disponer    <- solo arbitro

La columna "quién puede llamarla" NO la aplica este código: la aplicará la
política L7 de Cilium. Aquí solo se define la forma de los datos.

Todas las respuestas de agentes tienen la misma forma: {"resultados": [...]},
una lista porque el salto lateral devuelve dos intervenciones en una llamada.
"""
from __future__ import annotations

from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agents.triage import es_caso_para_deliberar
from schemas.caso import Case
from schemas.deliberacion import ContextoV1


class _Peticion(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PeticionEnriquecer(_Peticion):
    caso: Case          # completo: el Enriquecedor es el único que lo ve


class PeticionDebate(_Peticion):
    caso: Case          # recortado (agents.triage.caso_para_deliberar)
    contexto: ContextoV1
    historial: list[dict] = Field(default_factory=list)   # resultados previos serializados
    ronda: Literal[1, 2]


class PeticionArgumentar(PeticionDebate):
    # Si es True, después de su réplica el Investigador llama DIRECTAMENTE al
    # Defensor para el cierre, sin pasar por el Orquestador: el salto lateral.
    pedir_cierre: bool = False


class PeticionDeliberar(_Peticion):
    caso: Case          # recortado
    contexto: ContextoV1
    historial: list[dict] = Field(default_factory=list)
    presupuesto_agotado: bool = False


class RespuestaAgente(BaseModel):
    resultados: list[dict]
    # Llamadas que este componente hizo a otros mientras atendía la petición
    # (incluidas las de quien él llamó). Carril izquierdo del panel.
    llamadas: list[dict] = Field(default_factory=list)
    # Eventos de la capa de contenido (guardrail y acciones del Demo 2). Solo
    # el Enriquecedor los llena; los demás lo dejan vacío.
    seguridad_contenido: list[dict] = Field(default_factory=list)


def exigir_caso_recortado(caso: Case) -> None:
    """
    Quien debate rechaza un caso con datos del sujeto.

    Defensa en profundidad de la matriz de permisos: si el Orquestador tuviera
    un error y mandara el caso completo, el dato no se procesa. (Que el dato
    ya viajó por la red no lo evita esto; eso lo evita el Orquestador.)
    """
    if not es_caso_para_deliberar(caso):
        raise HTTPException(status_code=422, detail="caso con datos del sujeto: solo se acepta el caso recortado")
