"""
Esquema de caso, neutral al dominio.

Un "caso" es una alerta que alguien tiene que revisar: la regla que disparó,
el sujeto al que se refiere y la evidencia reunida. El mismo esquema sirve
para alertas de monitoreo transaccional (AML) y para alertas de un SOC, por
eso aquí NO aparece vocabulario de ningún dominio: nada de cliente, monto ni
cuenta. Lo específico de cada dominio va en los diccionarios `attributes`.

El campo que hace todo el trabajo de seguridad es `source_trust`: marca qué
partes del contexto escribió alguien de fuera. La inyección de prompts vive
siempre en un `free_text` con `source_trust="external"`, y la UI lo pinta
distinto para que la sala vea de dónde viene el veneno.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# "internal": lo generó un sistema propio (el motor de reglas, el core).
# "external": lo escribió un tercero (la glosa de una transferencia, el
# asunto de un correo, un documento adjunto). Es texto no controlado.
SourceTrust = Literal["internal", "external"]


class _Estricto(BaseModel):
    # extra="forbid": si un expediente trae un campo que el esquema no conoce,
    # falla al cargar. Preferimos enterarnos al preparar la demo y no cuando
    # un agente ignora en silencio un campo mal escrito.
    model_config = ConfigDict(extra="forbid")


class Trigger(_Estricto):
    """La regla que generó la alerta."""
    rule_id: str
    rule_name: str
    fired_at: str
    severity: Literal["baja", "media", "alta"]
    summary: str


class Subject(_Estricto):
    """A quién se refiere la alerta. Solo el Enriquecedor ve este bloque."""
    id: str
    display_name: str
    declared_context: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class Evidence(_Estricto):
    """Una pieza de evidencia: un movimiento, un evento de log, un documento."""
    id: str
    ts: str
    kind: str
    summary: str
    free_text: str = ""
    source_trust: SourceTrust
    attributes: dict[str, Any] = Field(default_factory=dict)


class HistoryItem(_Estricto):
    """Alertas o revisiones anteriores sobre el mismo sujeto."""
    ts: str
    summary: str
    outcome: str = ""


class PolicyExcerpt(_Estricto):
    """Fragmento de política interna que los agentes pueden citar por `id`."""
    id: str
    title: str
    text: str


class Case(_Estricto):
    case_id: str
    domain: str
    trigger: Trigger
    subject: Subject
    evidence: list[Evidence]
    history: list[HistoryItem] = Field(default_factory=list)
    policy_excerpts: list[PolicyExcerpt] = Field(default_factory=list)

    # ─── Ayudas para los agentes y para la UI ───────────────────────────────

    def evidence_ids(self) -> set[str]:
        return {e.id for e in self.evidence}

    def policy_ids(self) -> set[str]:
        return {p.id for p in self.policy_excerpts}

    def external_text_share(self) -> float:
        """
        Fracción del texto de evidencia que viene de fuentes no controladas.

        Es la estadística del slide ("qué porcentaje del contexto lo escribió
        alguien de fuera"). Se mide en caracteres de `summary` + `free_text`,
        no en tokens: es una aproximación honesta y no depende del tokenizador
        de ningún modelo. Si se cita en pantalla, decir que es por caracteres.
        """
        total = 0
        externo = 0
        for e in self.evidence:
            n = len(e.summary) + len(e.free_text)
            total += n
            if e.source_trust == "external":
                externo += n
        return externo / total if total else 0.0


def load_case(path: str) -> Case:
    """Carga y valida un expediente desde JSON. Falla ruidosamente si no cuadra."""
    with open(path, encoding="utf-8") as f:
        return Case.model_validate_json(f.read())
