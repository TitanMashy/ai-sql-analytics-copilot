from fastapi import APIRouter, Depends, Request

from app.schemas.analytics import ErrorResponse
from app.schemas.generation import AskResponse, GeneratedQueryResponse, GenerationRequest
from app.services.generation import SQLGenerationService
from app.services.llm_dependencies import get_sql_generation_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post(
    "/generate",
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
) -> GeneratedQueryResponse:
    result = service.generate(payload.question, payload.conversation_context)
    return GeneratedQueryResponse(**result.__dict__)


@router.post(
    "/ask",
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
            "description": "Invalid question or unsupported mock question",
        },
        502: {"model": ErrorResponse, "description": "LLM provider or response error"},
    },
)
def ask_analytics(
    request: Request,
    payload: GenerationRequest,
    service: SQLGenerationService = Depends(get_sql_generation_service),  # noqa: B008
) -> AskResponse:
    result = service.ask(
        payload.question,
        request_id=request.state.request_id,
        conversation_context=payload.conversation_context,
    )
    return AskResponse(
        **result.generated.__dict__,
        columns=result.result.columns,
        rows=result.result.rows,
        row_count=result.result.row_count,
        execution_time_ms=result.result.execution_time_ms,
    )
