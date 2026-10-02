from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class RequestTelemetry:
    request_id: str
    conversation_id: str | None = None
    llm_latency_ms: float = 0.0
    sql_validation_latency_ms: float = 0.0
    sql_execution_latency_ms: float = 0.0
    repair_count: int = 0


_current_telemetry: ContextVar[RequestTelemetry | None] = ContextVar(
    "current_request_telemetry", default=None
)


def set_request_telemetry(telemetry: RequestTelemetry):
    return _current_telemetry.set(telemetry)


def reset_request_telemetry(token) -> None:
    _current_telemetry.reset(token)


def get_request_telemetry() -> RequestTelemetry | None:
    return _current_telemetry.get()
