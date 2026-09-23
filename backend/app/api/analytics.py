from fastapi import APIRouter, Depends, Request

from app.analytics.dependencies import get_analytics_query_service
from app.analytics.service import AnalyticsQueryService
from app.schemas.analytics import (
    AnalyticsQueryRequest,
    AnalyticsQueryResponse,
    AnalyticsValidationResponse,
    ErrorResponse,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post(
    "/query",
    response_model=AnalyticsQueryResponse,
    summary="Execute a read-only analytics query",
    description=(
        "Validate and execute one SELECT statement against the restricted analytics database."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Validation or query execution error"},
        404: {"model": ErrorResponse, "description": "Table not found"},
        408: {"model": ErrorResponse, "description": "Query timeout"},
    },
)
def execute_analytics_query(
    request: Request,
    payload: AnalyticsQueryRequest,
    service: AnalyticsQueryService = Depends(get_analytics_query_service),  # noqa: B008
) -> AnalyticsQueryResponse:
    result = service.execute(payload.sql, request_id=request.state.request_id)
    return AnalyticsQueryResponse(
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        execution_time_ms=result.execution_time_ms,
    )


@router.post(
    "/validate",
    response_model=AnalyticsValidationResponse,
    summary="Validate an analytics SQL statement",
    description=(
        "Run the conservative Sprint 3 SQL validation placeholder without executing the query."
    ),
    responses={422: {"model": ErrorResponse, "description": "Invalid request body"}},
)
def validate_analytics_query(
    payload: AnalyticsQueryRequest,
    service: AnalyticsQueryService = Depends(get_analytics_query_service),  # noqa: B008
) -> AnalyticsValidationResponse:
    result = service.validate(payload.sql)
    return AnalyticsValidationResponse(
        valid=result.valid,
        errors=result.errors,
        warnings=result.warnings,
    )
