"""
AGNTCY Protocol Emitter
Emits realistic SLIM envelope messages, OpenTelemetry spans, and Agent Directory events
for every inter-agent communication in the pipeline.
"""
from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineContext:
    session_id: str
    trace_id: str
    application_id: str
    emitter: "ProtocolEmitter"


class ProtocolEmitter:
    """Collects all protocol events during a pipeline run."""

    def __init__(self):
        self.slim_messages: list[dict] = []
        self.otel_spans: list[dict] = []
        self.dir_events: list[dict] = []
        self._span_starts: dict[str, float] = {}

    # ─── SLIM ──────────────────────────────────────────────────────────────

    def emit_slim_message(
        self,
        ctx: PipelineContext,
        from_agent: str,
        to_agent: str,
        message_type: str,
        payload: dict,
        pattern: str = "request-reply",
        latency_ms: int | None = None,
    ) -> dict:
        import json

        msg_id = str(uuid.uuid4())
        timestamp_ms = int(time.time() * 1000)

        # Construct realistic SLIM envelope per draft-mpsb-agntcy-slim spec
        envelope = {
            "slim_version": "0.1",
            "msg_id": msg_id,
            "session_id": ctx.session_id,
            "trace_id": ctx.trace_id,
            "timestamp_ms": timestamp_ms,
            "pattern": pattern,
            "message_type": message_type,
            "from": {
                "agent_id": from_agent,
                "did": f"did:agntcy:mortgage:{from_agent}",
            },
            "to": {
                "agent_id": to_agent,
                "did": f"did:agntcy:mortgage:{to_agent}",
            },
            "security": {
                "encryption": "MLS",
                "identity_verified": True,
                "signature_alg": "Ed25519",
            },
            "payload": {
                "schema": f"agntcy.mortgage.{to_agent.replace('-', '_')}.{message_type.lower()}",
                "size_bytes": len(json.dumps(payload)),
                "data": payload,
            },
            "latency_ms": latency_ms,
        }

        self.slim_messages.append(envelope)
        return envelope

    # ─── OTel ──────────────────────────────────────────────────────────────

    def start_span(
        self,
        ctx: PipelineContext,
        span_id: str,
        agent_id: str,
        parent_span_id: str | None = None,
    ):
        self._span_starts[span_id] = time.time()
        span = {
            "trace_id": ctx.trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "name": f"agent.{agent_id}",
            "agent_id": agent_id,
            "start_time_ms": int(time.time() * 1000),
            "end_time_ms": None,
            "duration_ms": None,
            "status": "UNSET",
            "attributes": {
                "agntcy.agent.id": agent_id,
                "agntcy.session.id": ctx.session_id,
                "agntcy.application.id": ctx.application_id,
                "agntcy.protocol": "SLIM/0.1",
            },
            "events": [],
        }
        self.otel_spans.append(span)
        return span

    def end_span(
        self,
        ctx: PipelineContext,
        span_id: str,
        duration_ms: int,
        status: str,
        error: str | None = None,
    ):
        for span in self.otel_spans:
            if span["span_id"] == span_id:
                span["end_time_ms"] = int(time.time() * 1000)
                span["duration_ms"] = duration_ms
                span["status"] = "OK" if status == "completed" else "ERROR"
                if error:
                    span["events"].append({
                        "name": "exception",
                        "timestamp_ms": int(time.time() * 1000),
                        "attributes": {"exception.message": error},
                    })
                break

    # ─── DIR ───────────────────────────────────────────────────────────────

    def emit_dir_event(
        self,
        ctx: PipelineContext,
        agent_id: str,
        agent_did: str,
        event_type: str,
        query_capability: str,
        matched_agents: int,
        identity_verified: bool,
    ) -> dict:
        event = {
            "event_id": str(uuid.uuid4()),
            "session_id": ctx.session_id,
            "timestamp_ms": int(time.time() * 1000),
            "event_type": event_type,           # ANNOUNCE | DISCOVER | RESOLVE
            "agent_id": agent_id,
            "agent_did": agent_did,
            "query_capability": query_capability,
            "matched_agents": matched_agents,
            "identity_verified": identity_verified,
            "oasf_version": "1.0",
            "registry": "agntcy.dir.mortgage",
        }
        self.dir_events.append(event)
        return event
