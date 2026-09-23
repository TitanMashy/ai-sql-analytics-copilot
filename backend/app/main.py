import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.analytics.service import AnalyticsServiceError
from app.api.analytics import router as analytics_router
from app.api.generation import router as generation_router
from app.api.health import router as health_router
from app.api.schema import router as schema_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.llm.provider import LLMProviderError

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title="AI SQL Analytics Copilot API", version="0.1.0")
app.include_router(health_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(generation_router, prefix="/api/v1")
app.include_router(schema_router, prefix="/api/v1")

logger = logging.getLogger(__name__)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    request.state.request_id = request_id
    started_at = perf_counter()
    response = await call_next(request)
    elapsed_ms = (perf_counter() - started_at) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "http request completed",
        extra={
            "request_id": request_id,
            "endpoint": request.url.path,
            "execution_time_ms": round(elapsed_ms, 2),
            "status_code": response.status_code,
        },
    )
    return response


@app.exception_handler(AnalyticsServiceError)
async def analytics_service_error_handler(
    request: Request, error: AnalyticsServiceError
) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.code, "message": error.message}},
    )


@app.exception_handler(LLMProviderError)
async def llm_provider_error_handler(request: Request, error: LLMProviderError) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.code, "message": error.message}},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, error: HTTPException) -> JSONResponse:
    del request
    code_by_status = {404: "TABLE_NOT_FOUND", 422: "INVALID_REQUEST"}
    code = code_by_status.get(error.status_code, "INTERNAL_ERROR")
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": code, "message": str(error.detail)}},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    del request, error
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "INVALID_REQUEST",
                "message": "Request validation failed.",
            }
        },
    )
