"""Liveness, readiness, and operator diagnostics.

* ``/health`` (liveness, in ``main``): the process is up; touches no dependency.
* ``/health/ready`` (readiness): can this instance serve traffic? Required dependencies (the
  application and analytics databases, and the rate limiter when it is configured to fail closed)
  return 503 when unavailable. Optional or degradable dependencies (an unconfigured LLM provider, an
  unreachable Redis while failing open) keep the instance in service and are reported as
  ``{"status": "degraded", "degraded": [...]}`` with HTTP 200, so an orchestrator never restarts a
  healthy container because a provider is down.
* ``/health/diagnostics``: a detailed, operator-only view (needs the operator token).
"""

import logging
from collections.abc import Callable
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.analytics.dependencies import get_analytics_query_service
from app.analytics.service import AnalyticsQueryService
from app.core import rate_limit
from app.core.config import Settings, get_settings
from app.core.ops_auth import authorize_operator
from app.db.session import get_db
from app.schemas.health import HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:  # noqa: B008
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        logger.warning(
            "Application database health check failed",
            extra={"error_type": type(error).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application database unavailable.",
        ) from error
    return HealthResponse(status="ok", database="ok")


def _secret_present(secret) -> bool:
    return bool(secret and secret.get_secret_value().strip())


def _provider_configured(settings: Settings) -> bool:
    return {
        "mock": True,
        "gemini": _secret_present(settings.gemini_api_key),
        "openai": _secret_present(settings.openai_api_key),
    }.get(settings.llm_mode, False)


def _rate_limiter_ping() -> float | None:
    """Seconds for a Redis round trip, or ``None`` when the limiter is in-process."""
    ping = getattr(rate_limit.rate_limiter, "ping", None)
    return ping() if callable(ping) else None


@router.get("/health/ready")
def readiness_check(
    request: Request,
    db: Session = Depends(get_db),  # noqa: B008
    analytics_service: AnalyticsQueryService = Depends(get_analytics_query_service),  # noqa: B008
) -> dict[str, Any]:
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        with analytics_service.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        logger.warning(
            "Analytics readiness check failed",
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "error_type": type(error).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A required database dependency is unavailable.",
        ) from error

    degraded: list[str] = []
    if not _provider_configured(settings):
        degraded.append("llm_provider")
    try:
        _rate_limiter_ping()
    except Exception as error:  # Redis unreachable (any client error)
        logger.warning(
            "Rate limiter backend readiness check failed",
            extra={"error_type": type(error).__name__},
        )
        if settings.rate_limit_fail_mode == "closed":
            # Requests cannot be admitted without the limiter, so this instance cannot serve.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="A required dependency is unavailable.",
            ) from error
        degraded.append("rate_limiter")

    if degraded:
        return {"status": "degraded", "degraded": degraded}
    return {"status": "ready"}


def _timed(check: Callable[[], Any]) -> dict[str, Any]:
    started_at = perf_counter()
    try:
        check()
    except Exception as error:
        return {
            "ok": False,
            "latency_ms": round((perf_counter() - started_at) * 1000, 2),
            "error_type": type(error).__name__,
        }
    return {"ok": True, "latency_ms": round((perf_counter() - started_at) * 1000, 2)}


def _pool_status(engine: Any) -> str | None:
    pool = getattr(engine, "pool", None)
    status_method = getattr(pool, "status", None)
    return status_method() if callable(status_method) else None


@router.get("/health/diagnostics", include_in_schema=False)
def diagnostics(
    request: Request,
    db: Session = Depends(get_db),  # noqa: B008
    analytics_service: AnalyticsQueryService = Depends(get_analytics_query_service),  # noqa: B008
):
    """Operator-only detail: dependency latency, pool state, schema revision, active features.

    Never returns URLs, credentials, or tokens.
    """
    settings = get_settings()
    denied = authorize_operator(request, settings)
    if denied is not None:
        return denied

    def application_database() -> None:
        db.execute(text("SELECT 1"))

    def analytics_database() -> None:
        with analytics_service.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    revision: str | None
    try:
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except SQLAlchemyError:
        db.rollback()
        revision = None

    rate_limiter_check = _timed(_rate_limiter_ping)
    return JSONResponse(
        {
            "version": settings.app_version,
            "environment": settings.environment,
            "migration_revision": revision,
            "checks": {
                "application_database": _timed(application_database),
                "analytics_database": _timed(analytics_database),
                "rate_limiter": {"backend": settings.rate_limit_backend, **rate_limiter_check},
                "llm_provider": {
                    "mode": settings.llm_mode,
                    "configured": _provider_configured(settings),
                },
            },
            "pools": {
                "application": _pool_status(db.get_bind()),
                "analytics": _pool_status(analytics_service.engine),
            },
            "features": {
                "auth_mode": settings.auth_mode,
                "conversation_store": settings.conversation_store,
                "rate_limit_backend": settings.rate_limit_backend,
                "rate_limit_fail_mode": settings.rate_limit_fail_mode,
                "sql_cache_enabled": settings.sql_cache_enabled,
                "audit_sink": settings.audit_sink,
                "tracing_enabled": settings.otel_enabled,
                "query_cost_limit": settings.query_cost_limit,
                "direct_sql_endpoints": settings.direct_sql_endpoints_enabled,
            },
        }
    )
