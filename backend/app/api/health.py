import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.analytics.dependencies import get_analytics_query_service
from app.analytics.service import AnalyticsQueryService
from app.core.config import get_settings
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


@router.get("/health/ready")
def readiness_check(
    request: Request,
    db: Session = Depends(get_db),  # noqa: B008
    analytics_service: AnalyticsQueryService = Depends(get_analytics_query_service),  # noqa: B008
) -> dict[str, str]:
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

    settings = get_settings()
    configured_key = (
        settings.gemini_api_key.get_secret_value().strip()
        if settings.gemini_api_key
        else ""
    )
    openai_key = (
        settings.openai_api_key.get_secret_value().strip()
        if settings.openai_api_key
        else ""
    )
    provider_is_configured = {
        "mock": True,
        "gemini": bool(configured_key),
        "openai": bool(openai_key),
    }.get(settings.llm_mode, False)
    if not provider_is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The configured analytics provider is unavailable.",
        )
    return {"status": "ready"}
