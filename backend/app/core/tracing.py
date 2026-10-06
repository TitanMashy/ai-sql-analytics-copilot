"""Optional OpenTelemetry tracing.

Disabled by default and a no-op unless ``OTEL_ENABLED=true``: the OpenTelemetry packages are
imported lazily, so a deployment that does not trace does not need them installed. Spans cover the
request, the LLM call, SQL validation, and SQL execution. Attributes are limited to identifiers and
counts (request id, provider, row count, status); question text and SQL are never attached.

``OTEL_EXPORTER_OTLP_ENDPOINT`` selects an OTLP/HTTP collector; without it spans are created but
not exported (useful in tests). Install the extra with ``pip install -e ".[tracing]"``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.core.config import Settings

logger = logging.getLogger(__name__)

_tracer: Any | None = None

# Attribute names that must never be set on a span.
_FORBIDDEN_ATTRIBUTES = frozenset({"question", "sql", "query", "prompt", "token", "authorization"})


def configure_tracing(settings: Settings) -> bool:
    """Install the tracer provider. Returns True when tracing is active."""
    global _tracer
    _tracer = None
    if not settings.otel_enabled:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OTEL_ENABLED is set but the OpenTelemetry packages are not installed")
        return False

    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": settings.otel_service_name, "service.version": settings.app_version}
        )
    )
    if settings.otel_exporter_otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError:
            logger.warning("OTLP exporter package is not installed; spans will not be exported")
        else:
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
            )
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("analytics-copilot")
    return True


def tracing_enabled() -> bool:
    return _tracer is not None


@contextmanager
def span(name: str, **attributes: str | int | float | bool | None) -> Iterator[Any | None]:
    """Run a block inside a span; a no-op when tracing is disabled."""
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None and key.casefold() not in _FORBIDDEN_ATTRIBUTES:
                current.set_attribute(key, value)
        yield current


def set_span_attribute(current: Any | None, key: str, value: str | int | float | bool) -> None:
    if current is not None and key.casefold() not in _FORBIDDEN_ATTRIBUTES:
        current.set_attribute(key, value)


def record_span_error(current: Any | None, error_code: str) -> None:
    """Mark a span failed using a stable error code (never the exception message)."""
    if current is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        current.set_status(Status(StatusCode.ERROR, error_code))
    except ImportError:  # pragma: no cover - tracing active implies the package exists
        return
    current.set_attribute("error.code", error_code)
