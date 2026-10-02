import logging
from time import perf_counter

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.analytics.service import AnalyticsServiceError
from app.api.analytics import router as analytics_router
from app.api.conversations import router as conversations_router
from app.api.generation import router as generation_router
from app.api.health import readiness_check
from app.api.health import router as health_router
from app.api.schema import router as schema_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.metrics import metrics
from app.core.middleware import (
    RequestSizeLimitMiddleware,
    SlidingWindowRateLimiter,
    request_id_from_headers,
)
from app.core.telemetry import (
    RequestTelemetry,
    reset_request_telemetry,
    set_request_telemetry,
)
from app.llm.provider import LLMProviderError

settings = get_settings()
configure_logging(settings.effective_log_level)

app = FastAPI(
    title="AI SQL Analytics Copilot API",
    version="0.1.0",
    debug=settings.effective_debug,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)
app.include_router(health_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(generation_router, prefix="/api/v1")
app.include_router(conversations_router, prefix="/api/v1")
app.include_router(schema_router, prefix="/api/v1")
app.add_api_route("/health", lambda: {"status": "ok"}, methods=["GET"], include_in_schema=False)
app.add_api_route(
    "/health/ready", readiness_check, methods=["GET"], include_in_schema=False
)
app.add_api_route("/api/v1/metrics", lambda: metrics.snapshot(), methods=["GET"])
app.add_middleware(
    RequestSizeLimitMiddleware,
    max_body_bytes=settings.max_request_body_bytes,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

rate_limiter = SlidingWindowRateLimiter(
    settings.rate_limit_requests, settings.rate_limit_window_seconds
)

logger = logging.getLogger(__name__)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = getattr(request.state, "request_id", None) or request_id_from_headers(
        request.headers.raw
    )
    request.state.request_id = request_id
    telemetry = RequestTelemetry(request_id=request_id)
    token = set_request_telemetry(telemetry)
    started_at = perf_counter()
    path = request.url.path
    endpoint_key = _rate_limit_endpoint(path, request.method)
    try:
        try:
            if endpoint_key and settings.rate_limit_enabled:
                client_id = request.client.host if request.client else "unknown"
                allowed, retry_after = rate_limiter.check(f"{client_id}:{endpoint_key}")
                if not allowed:
                    metrics.increment("rate_limit_responses_total")
                    response = JSONResponse(
                        status_code=429,
                        content={
                            "error": {
                                "code": "RATE_LIMIT_EXCEEDED",
                                "message": "Too many requests. Please retry later.",
                                "request_id": request_id,
                            }
                        },
                        headers={"Retry-After": str(retry_after)},
                    )
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        except Exception as error:
            logger.error(
                "unhandled request failure",
                extra={
                    "request_id": request_id,
                    "endpoint": path,
                    "error_type": type(error).__name__,
                },
            )
            response = _internal_error_response(request_id)

        elapsed_ms = (perf_counter() - started_at) * 1000
        response.headers["X-Request-ID"] = request_id
        _add_security_headers(response)
        telemetry.conversation_id = telemetry.conversation_id or getattr(
            request.state, "conversation_id", None
        )
        route = request.scope.get("route")
        endpoint = getattr(route, "path", path)
        if _is_analytics_request(path, request.method):
            metrics.record_analytics_request(response.status_code, elapsed_ms)
        logger.info(
            "http request completed",
            extra={
                "request_id": request_id,
                "conversation_id": telemetry.conversation_id,
                "endpoint": endpoint,
                "request_duration_ms": round(elapsed_ms, 2),
                "llm_latency_ms": round(telemetry.llm_latency_ms, 2),
                "sql_validation_duration_ms": round(telemetry.sql_validation_latency_ms, 2),
                "sql_execution_duration_ms": round(telemetry.sql_execution_latency_ms, 2),
                "repair_count": telemetry.repair_count,
                "status_code": response.status_code,
            },
        )
        return response
    finally:
        reset_request_telemetry(token)


@app.exception_handler(AnalyticsServiceError)
async def analytics_service_error_handler(
    request: Request, error: AnalyticsServiceError
) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


@app.exception_handler(LLMProviderError)
async def llm_provider_error_handler(request: Request, error: LLMProviderError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, error: HTTPException) -> JSONResponse:
    code_by_status = {
        413: "REQUEST_TOO_LARGE",
        422: "INVALID_REQUEST",
        429: "RATE_LIMIT_EXCEEDED",
        503: "DEPENDENCY_UNAVAILABLE",
    }
    if error.status_code == 404:
        code = (
            "CONVERSATION_NOT_FOUND"
            if request.url.path.startswith("/api/v1/analytics/conversations/")
            else "TABLE_NOT_FOUND"
        )
    else:
        code = code_by_status.get(error.status_code, "INTERNAL_ERROR")
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": code,
                "message": str(error.detail),
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    del error
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "INVALID_REQUEST",
                "message": "Request validation failed.",
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, error: Exception) -> JSONResponse:
    logger.error(
        "unhandled request failure",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "endpoint": request.url.path,
            "error_type": type(error).__name__,
        },
    )
    response = _internal_error_response(getattr(request.state, "request_id", None))
    _add_security_headers(response)
    return response


def _internal_error_response(request_id: str | None) -> JSONResponse:
    response = JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "The request could not be completed.",
                "request_id": request_id,
            }
        },
        headers={"X-Request-ID": request_id} if request_id else None,
    )
    _add_security_headers(response)
    return response


def _rate_limit_endpoint(path: str, method: str) -> str | None:
    if method != "POST":
        return None
    if path == "/api/v1/analytics/generate":
        return "generate"
    if path == "/api/v1/analytics/ask":
        return "ask"
    if path == "/api/v1/analytics/conversations" or (
        path.startswith("/api/v1/analytics/conversations/") and path.endswith("/turns")
    ):
        return "conversation"
    return None


def _is_analytics_request(path: str, method: str) -> bool:
    return method == "POST" and path.startswith("/api/v1/analytics/")


def _add_security_headers(response) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
