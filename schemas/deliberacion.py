"""
Mensajes de la deliberación: lo que la sala lee en el bus SLIM.

    Enriquecedor  ->  ContextoV1    (hechos normalizados, sin nombre del sujeto)
    Investigador  ->  ArgumentoV1   (argumenta que hay riesgo)
    Defensor      ->  ObjecionV1    (argumenta que hay explicación legítima)
    Árbitro       ->  DisposicionV1 (decide y redacta; un humano confirma)

Decisión de diseño: cada afirmación es un `Punto` que lleva los `id` de la
evidencia y de la política que invoca. Así un argumento se puede verificar
mecánicamente contra el expediente, y en pantalla se puede resaltar la
evidencia citada. Un punto sin evidencia es una generalidad, y el esquema no
la acepta.

Estos modelos también sirven como esquema JSON para pedirle salida
estructurada al LLM (`Modelo.model_json_schema()`).
"""
from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.caso import Case, SourceTrust


class _Mensaje(BaseModel):
    # Aquí NO usamos extra="forbid": un modelo pequeño a veces agrega un campo
    # de más. Lo ignoramos en vez de tirar la ronda completa por eso.
    model_config = ConfigDict(extra="ignore")

    # En la segunda corrida real el modelo repitió ids dentro de la misma
    # lista ("ev-001, ev-002, ..., ev-001, ev-002"). Quitar duplicados no
    # cambia lo que se afirma, así que se normaliza en vez de rechazar.
    @field_validator("evidencia", "politica", mode="after", check_fields=False)
    @classmethod
    def _sin_duplicados(cls, ids: list[str]) -> list[str]:
        return list(dict.fromkeys(ids))


class Punto(_Mensaje):
    """Una afirmación concreta, anclada en evidencia."""
    # Límites de largo: la gramática de Ollama los hace cumplir al generar.
    # Mantienen el debate legible proyectado y bajan el costo en tokens.
    afirmacion: str = Field(max_length=320)
    evidencia: list[str] = Field(min_length=1, max_length=4, description="ids de evidencia citados, p.ej. ['ev-003']")
    politica: list[str] = Field(default_factory=list, max_length=3, description="ids de política citados")


class HechoV1(_Mensaje):
    """Un hecho normalizado por el Enriquecedor."""
    hecho: str = Field(max_length=320, description="el hecho en una oración, con cifras y fechas; sin el nombre del sujeto")
    evidencia: list[str] = Field(min_length=1, max_length=6, description="ids de evidencia de los que sale este hecho")
    # Lo fija el CÓDIGO a partir de source_trust de la evidencia citada, no el
    # modelo: la procedencia no puede depender de lo que el modelo diga.
    origen: SourceTrust | None = None


class ContextoV1(_Mensaje):
    """Lo que el Enriquecedor entrega al resto del equipo.

    Es la frontera de la matriz de permisos: Investigador, Defensor y Árbitro
    reciben esto, nunca el expediente crudo. Por eso no lleva el nombre del
    sujeto ni el texto externo tal cual, solo hechos con su procedencia.
    """
    schema_id: Literal["contexto.v1"] = "contexto.v1"
    resumen: str = Field(max_length=600, description="dos oraciones: qué disparó la alerta y qué muestra la evidencia")
    # El tope real por expediente (número de piezas de evidencia) se fija en
    # esquema_para_llm; aquí solo un límite de cordura.
    hechos: list[HechoV1] = Field(min_length=1, max_length=60)


class PuntoObjecion(Punto):
    """Un punto del Defensor: además dice qué afirmación del Investigador rebate."""
    objeta: str = Field(max_length=160, description="la afirmación del Investigador que se rebate, en pocas palabras")


class ArgumentoV1(_Mensaje):
    schema_id: Literal["argumento.v1"] = "argumento.v1"
    ronda: Literal[1, 2]
    tesis: str = Field(max_length=300, description="una oración: por qué este caso merece escalarse")
    puntos: list[Punto] = Field(min_length=1, max_length=3)
    confianza: Literal["baja", "media", "alta"]


class ObjecionV1(_Mensaje):
    schema_id: Literal["objecion.v1"] = "objecion.v1"
    ronda: Literal[1, 2]
    tesis: str = Field(max_length=300, description="una oración: cuál es la explicación legítima")
    puntos: list[PuntoObjecion] = Field(min_length=1, max_length=3)
    confianza: Literal["baja", "media", "alta"]


# Recomendaciones neutrales al dominio: sirven igual para AML que para SOC.
Recomendacion = Literal["escalar", "cerrar_falso_positivo", "pedir_informacion"]


class DisposicionV1(_Mensaje):
    schema_id: Literal["disposicion.v1"] = "disposicion.v1"
    recomendacion: Recomendacion
    prevalece: Literal["investigador", "defensor", "ninguno"]
    fundamento: str = Field(max_length=700, description="dos o tres oraciones que un revisor humano pueda firmar")
    puntos_decisivos: list[Punto] = Field(min_length=1, max_length=3)

    # Estos dos campos NO los decide el modelo; los fija el código.
    # - presupuesto_agotado: lo marca el Orquestador si se acabaron los tokens
    #   antes de terminar las dos rondas (control de admisión, sección 3).
    # - requiere_confirmacion_humana: siempre True. El Árbitro nunca cierra un
    #   caso por su cuenta; ese límite es lo que mantiene creíble la premisa.
    presupuesto_agotado: bool = False
    requiere_confirmacion_humana: Literal[True] = True


Mensaje = ContextoV1 | ArgumentoV1 | ObjecionV1 | DisposicionV1


# Campos que decide el código y que el modelo NO debe poder escribir.
CAMPOS_DEL_CODIGO = {"schema_id", "ronda", "presupuesto_agotado", "requiere_confirmacion_humana", "origen"}


def esquema_para_llm(
    modelo: type[BaseModel],
    evidencia_ids: list[str] | None = None,
    politica_ids: list[str] | None = None,
    max_items: dict[str, int] | None = None,
) -> dict:
    """
    JSON Schema que se le pasa a Ollama como formato de salida.

    Ajustes sobre `model_json_schema()`:
    1. Quita CAMPOS_DEL_CODIGO: si el modelo no los ve, no los puede inventar.
    2. Marca como obligatorios todos los campos restantes, para que la
       gramática obligue a llenarlos (p.ej. `politica`, aunque sea vacía).
    3. Sustituye cada `$ref` por la definición completa. Así no dependemos de
       que el convertidor de esquema a gramática de Ollama resuelva referencias.
    4. Si se pasan los ids del expediente, las listas `evidencia` y `politica`
       solo aceptan esos valores (enum). En la primera corrida real el modelo
       puso "pol-5.2" dentro de `evidencia`; con esto no puede generar un id
       que no exista ni mezclar los dos tipos. `citas_invalidas` se conserva
       como segunda línea para backends sin decodificación guiada.
    5. `max_items` fija topes de listas por expediente, p.ej. {"hechos": 8}:
       en la segunda corrida el Enriquecedor repitió hechos hasta llenar el
       máximo y dejó fuera la evidencia del final.
    """
    max_items = max_items or {}
    restricciones = {}
    if evidencia_ids:
        restricciones["evidencia"] = sorted(evidencia_ids)
    if politica_ids:
        restricciones["politica"] = sorted(politica_ids)
    esquema = modelo.model_json_schema()
    definiciones = esquema.pop("$defs", {})

    def resolver(nodo):
        if isinstance(nodo, dict):
            if "$ref" in nodo:
                nombre = nodo["$ref"].split("/")[-1]
                return resolver(copy.deepcopy(definiciones[nombre]))
            nodo = {k: resolver(v) for k, v in nodo.items()}
            if "properties" in nodo:
                for campo in CAMPOS_DEL_CODIGO:
                    nodo["properties"].pop(campo, None)
                for campo, valores in restricciones.items():
                    if campo in nodo["properties"]:
                        nodo["properties"][campo]["items"] = {"type": "string", "enum": valores}
                for campo, tope in max_items.items():
                    if campo in nodo["properties"]:
                        nodo["properties"][campo]["maxItems"] = tope
                nodo["required"] = list(nodo["properties"])
            return nodo
        if isinstance(nodo, list):
            return [resolver(x) for x in nodo]
        return nodo

    return resolver(esquema)


def citas_invalidas(mensaje: Mensaje, caso: Case) -> list[str]:
    """
    Devuelve los ids citados que NO existen en el expediente.

    Lista vacía = todas las citas son reales. Si no está vacía, el agente
    alucinó una referencia. No lo corregimos en silencio: la UI debe poder
    mostrarlo, porque "no afirmar que algo está verificado si no lo está"
    aplica también a lo que dicen los agentes.
    """
    evidencia_ok = caso.evidence_ids()
    politica_ok = caso.policy_ids()
    if isinstance(mensaje, DisposicionV1):
        puntos = mensaje.puntos_decisivos
    elif isinstance(mensaje, ContextoV1):
        puntos = mensaje.hechos
    else:
        puntos = mensaje.puntos

    malas: list[str] = []
    for p in puntos:
        malas += [f"evidencia:{i}" for i in p.evidencia if i not in evidencia_ok]
        malas += [f"politica:{i}" for i in getattr(p, "politica", []) if i not in politica_ok]
    return malas
