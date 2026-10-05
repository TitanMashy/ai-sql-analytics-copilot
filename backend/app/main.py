import hmac
import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.analytics.service import AnalyticsServiceError
from app.api.analytics import router as analytics_router
from app.api.conversations import router as conversations_router
from app.api.generation import router as generation_router
from app.api.health import readiness_check
from app.api.health import router as health_router
from app.api.schema import router as schema_router
from app.conversation.service import ConversationAccessError
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.metrics import metrics
from app.core.middleware import (
    RequestSizeLimitMiddleware,
    request_id_from_headers,
)
from app.core.rate_limit import RateLimitExceeded
from app.core.telemetry import (
    RequestTelemetry,
    reset_request_telemetry,
    set_request_telemetry,
)
from app.llm.provider import LLMProviderError

settings = get_settings()
configure_logging(settings.effective_log_level)

logger = logging.getLogger(__name__)
if settings.auth_mode != "jwt":
    logger.warning(
        "AUTH_MODE=%s does not enforce signed tokens; do not use in production",
        settings.auth_mode,
    )

app = FastAPI(
    title="AI SQL Analytics Copilot API",
    version="0.1.0",
    debug=settings.effective_debug,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)
app.include_router(health_router, prefix="/api/v1")
if settings.direct_sql_endpoints_enabled:
    # /query and /validate run caller-written SQL. They are not mounted in production unless
    # ENABLE_DIRECT_SQL_ENDPOINTS is set explicitly.
    app.include_router(analytics_router, prefix="/api/v1")
app.include_router(generation_router, prefix="/api/v1")
app.include_router(conversations_router, prefix="/api/v1")
app.include_router(schema_router, prefix="/api/v1")
app.add_api_route("/health", lambda: {"status": "ok"}, methods=["GET"], include_in_schema=False)
app.add_api_route(
    "/health/ready", readiness_check, methods=["GET"], include_in_schema=False
)


def metrics_snapshot(request: Request) -> JSONResponse:
    """Process-local metrics. Bearer-protected when METRICS_TOKEN is set.

    With no token configured the endpoint is open outside production and disabled (404) in
    production, so an unconfigured deployment never exposes it.
    """
    request_id = getattr(request.state, "request_id", None)
    configured = settings.metrics_token.get_secret_value() if settings.metrics_token else ""
    if not configured:
        if settings.is_production:
            return _error_response(404, "NOT_FOUND", "Not found.", request_id)
        return JSONResponse(metrics.snapshot())
    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        supplied.strip().encode(), configured.encode()
    ):
        return _error_response(
            401,
            "UNAUTHENTICATED",
            "A valid metrics token is required.",
            request_id,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return JSONResponse(metrics.snapshot())


app.add_api_route("/api/v1/metrics", metrics_snapshot, methods=["GET"], include_in_schema=False)
app.add_middleware(
    RequestSizeLimitMiddleware,
    max_body_bytes=settings.max_request_body_bytes,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After"],
)


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
    try:
        try:
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


def _error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str | None,
    headers: dict[str, str] | None = None,
    debug: dict | None = None,
) -> JSONResponse:
    error: dict = {"code": code, "message": message, "request_id": request_id}
    if debug and not settings.is_production:
        error["debug"] = debug
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, error: RateLimitExceeded) -> JSONResponse:
    return _error_response(
        429,
        "RATE_LIMIT_EXCEEDED",
        "Too many requests. Please retry later.",
        getattr(request.state, "request_id", None),
        headers={"Retry-After": str(error.retry_after)},
    )


@app.exception_handler(ConversationAccessError)
async def conversation_access_handler(
    request: Request, error: ConversationAccessError
) -> JSONResponse:
    del error
    return _error_response(
        404,
        "CONVERSATION_NOT_FOUND",
        "Conversation not found.",
        getattr(request.state, "request_id", None),
    )


@app.exception_handler(AnalyticsServiceError)
async def analytics_service_error_handler(
    request: Request, error: AnalyticsServiceError
) -> JSONResponse:
    return _error_response(
        error.status_code,
        error.code,
        error.message,
        getattr(request.state, "request_id", None),
        debug=error.debug,
    )


@app.exception_handler(LLMProviderError)
async def llm_provider_error_handler(request: Request, error: LLMProviderError) -> JSONResponse:
    return _error_response(
        error.status_code,
        error.code,
        error.message,
        getattr(request.state, "request_id", None),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
    code_by_status = {
        401: "UNAUTHENTICATED",
        403: "FORBIDDEN",
        405: "METHOD_NOT_ALLOWED",
        413: "REQUEST_TOO_LARGE",
        422: "INVALID_REQUEST",
        429: "RATE_LIMIT_EXCEEDED",
        503: "DEPENDENCY_UNAVAILABLE",
    }
    if error.status_code == 404:
        if request.url.path.startswith("/api/v1/analytics/conversations/"):
            code = "CONVERSATION_NOT_FOUND"
        elif request.url.path.startswith("/api/v1/schema/tables/"):
            code = "TABLE_NOT_FOUND"
        else:
            code = "NOT_FOUND"
    else:
        code = code_by_status.get(error.status_code, "INTERNAL_ERROR")
    return _error_response(
        error.status_code,
        code,
        str(error.detail),
        getattr(request.state, "request_id", None),
        headers=dict(error.headers) if error.headers else None,
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    del error
    return _error_response(
        422,
        "INVALID_REQUEST",
        "Request validation failed.",
        getattr(request.state, "request_id", None),
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


def _is_analytics_request(path: str, method: str) -> bool:
    return method == "POST" and path.startswith("/api/v1/analytics/")


def _add_security_headers(response) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
