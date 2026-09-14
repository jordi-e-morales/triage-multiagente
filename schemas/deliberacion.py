"""
Mensajes de la deliberación: lo que la sala lee en el bus SLIM.

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

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.caso import Case


class _Mensaje(BaseModel):
    # Aquí NO usamos extra="forbid": un modelo pequeño a veces agrega un campo
    # de más. Lo ignoramos en vez de tirar la ronda completa por eso.
    model_config = ConfigDict(extra="ignore")


class Punto(_Mensaje):
    """Una afirmación concreta, anclada en evidencia."""
    afirmacion: str
    evidencia: list[str] = Field(min_length=1, description="ids de evidencia citados, p.ej. ['ev-003']")
    politica: list[str] = Field(default_factory=list, description="ids de política citados")


class PuntoObjecion(Punto):
    """Un punto del Defensor: además dice qué afirmación del Investigador rebate."""
    objeta: str = Field(description="la afirmación del Investigador que se rebate, en pocas palabras")


class ArgumentoV1(_Mensaje):
    schema_id: Literal["argumento.v1"] = "argumento.v1"
    ronda: Literal[1, 2]
    tesis: str = Field(description="una oración: por qué este caso merece escalarse")
    puntos: list[Punto] = Field(min_length=1, max_length=4)
    confianza: Literal["baja", "media", "alta"]


class ObjecionV1(_Mensaje):
    schema_id: Literal["objecion.v1"] = "objecion.v1"
    ronda: Literal[1, 2]
    tesis: str = Field(description="una oración: cuál es la explicación legítima")
    puntos: list[PuntoObjecion] = Field(min_length=1, max_length=4)
    confianza: Literal["baja", "media", "alta"]


# Recomendaciones neutrales al dominio: sirven igual para AML que para SOC.
Recomendacion = Literal["escalar", "cerrar_falso_positivo", "pedir_informacion"]


class DisposicionV1(_Mensaje):
    schema_id: Literal["disposicion.v1"] = "disposicion.v1"
    recomendacion: Recomendacion
    prevalece: Literal["investigador", "defensor", "ninguno"]
    fundamento: str = Field(description="dos o tres oraciones que un revisor humano pueda firmar")
    puntos_decisivos: list[Punto] = Field(min_length=1, max_length=3)

    # Estos dos campos NO los decide el modelo; los fija el código.
    # - presupuesto_agotado: lo marca el Orquestador si se acabaron los tokens
    #   antes de terminar las dos rondas (control de admisión, sección 3).
    # - requiere_confirmacion_humana: siempre True. El Árbitro nunca cierra un
    #   caso por su cuenta; ese límite es lo que mantiene creíble la premisa.
    presupuesto_agotado: bool = False
    requiere_confirmacion_humana: Literal[True] = True


Mensaje = ArgumentoV1 | ObjecionV1 | DisposicionV1


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
    puntos = mensaje.puntos_decisivos if isinstance(mensaje, DisposicionV1) else mensaje.puntos

    malas: list[str] = []
    for p in puntos:
        malas += [f"evidencia:{i}" for i in p.evidencia if i not in evidencia_ok]
        malas += [f"politica:{i}" for i in p.politica if i not in politica_ok]
    return malas
