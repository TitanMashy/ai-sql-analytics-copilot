from fastapi import APIRouter, Depends, Request

from app.core.auth import Principal, get_principal
from app.core.rate_limit import enforce_rate_limit
from app.schemas.analytics import ErrorResponse
from app.schemas.generation import (
    AskResponse,
    GeneratedQueryResponse,
    GenerationRequest,
    KPIResponse,
    VisualizationAxisResponse,
    VisualizationResponse,
)
from app.services.generation import SQLGenerationService
from app.services.llm_dependencies import get_sql_generation_service

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(get_principal)],  # noqa: B008
)


@router.post(
    "/generate",
    dependencies=[Depends(enforce_rate_limit("llm"))],  # noqa: B008
    response_model=GeneratedQueryResponse,
    summary="Generate SQL from a natural-language question",
    description=(
        "Retrieve relevant schema, ask the configured LLM provider for structured SQL, "
        "and return the SQL without executing it."
    ),
    responses={
        422: {
            "model": ErrorResponse,
            "description": "Invalid question or unsupported mock question",
        },
        502: {"model": ErrorResponse, "description": "LLM provider or response error"},
        503: {"model": ErrorResponse, "description": "LLM configuration error"},
    },
)
def generate_sql(
    payload: GenerationRequest,
    service: SQLGenerationService = Depends(get_sql_generation_service),  # noqa: B008
    principal: Principal = Depends(get_principal),  # noqa: B008
) -> GeneratedQueryResponse:
    result = service.generate(
        payload.question,
        payload.conversation_context,
        conversation_id=payload.conversation_id,
        principal=principal,
    )
    return GeneratedQueryResponse(**result.__dict__)


@router.post(
    "/ask",
    dependencies=[Depends(enforce_rate_limit("llm"))],  # noqa: B008
    response_model=AskResponse,
    summary="Generate and execute analytics SQL",
    description=(
        "Generate SQL, pass it through the existing validator, execute it on the read-only "
        "analytics database, and return normalized results."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Generated SQL rejected or execution error"},
        404: {"model": ErrorResponse, "description": "Generated query table not found"},
        408: {"model": ErrorResponse, "description": "Query timeout"},
        422: {
            "model": ErrorResponse,
            "description": (
                "Invalid question, unsupported mock question, or no valid query could be produced"
            ),
        },
        502: {"model": ErrorResponse, "description": "LLM provider or response error"},
        504: {"model": ErrorResponse, "description": "Request deadline exceeded"},
    },
)
def ask_analytics(
    request: Request,
    payload: GenerationRequest,
    service: SQLGenerationService = Depends(get_sql_generation_service),  # noqa: B008
    principal: Principal = Depends(get_principal),  # noqa: B008
) -> AskResponse:
    result = service.ask(
        payload.question,
        request_id=request.state.request_id,
        conversation_context=payload.conversation_context,
        conversation_id=payload.conversation_id,
        principal=principal,
    )
    kpi = result.analysis.kpi
    visualization = result.analysis.visualization
    return AskResponse(
        **result.generated.__dict__,
        columns=result.result.columns,
        rows=result.result.rows,
        row_count=result.result.row_count,
        execution_time_ms=result.result.execution_time_ms,
        truncated=result.result.truncated,
        summary=result.summary,
        kpi=KPIResponse(**kpi.__dict__) if kpi else None,
        visualization=(
            VisualizationResponse(
                type=visualization.type,
                title=visualization.title,
                x_axis=(
                    VisualizationAxisResponse(**visualization.x_axis.__dict__)
                    if visualization.x_axis
                    else None
                ),
                y_axis=(
                    VisualizationAxisResponse(**visualization.y_axis.__dict__)
                    if visualization.y_axis
                    else None
                ),
                series=[
                    VisualizationAxisResponse(**axis.__dict__) for axis in visualization.series
                ],
            )
            if visualization
            else None
        ),
        warnings=result.analysis.warnings,
    )
