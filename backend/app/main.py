import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.analytics.service import AnalyticsServiceError
from app.api.analytics import router as analytics_router
from app.api.conversations import router as conversations_router
from app.api.feedback import router as feedback_router
from app.api.generation import router as generation_router
from app.api.health import readiness_check
from app.api.health import router as health_router
from app.api.schema import router as schema_router
from app.conversation.service import ConversationAccessError, get_conversation_memory
from app.core.config import ConfigurationError, get_settings
from app.core.logging import configure_logging
from app.core.metrics import CONTENT_TYPE_PROMETHEUS, metrics
from app.core.middleware import (
    RequestSizeLimitMiddleware,
    request_id_from_headers,
)
from app.core.ops_auth import authorize_operator, error_response
from app.core.rate_limit import RateLimitExceeded
from app.core.telemetry import (
    RequestTelemetry,
    reset_request_telemetry,
    set_request_telemetry,
)
from app.llm.provider import LLMProviderError

try:
    settings = get_settings()
except ConfigurationError as configuration_error:
    # Fail at startup with every problem named (and no values), not with a stack trace.
    raise SystemExit(str(configuration_error)) from None
configure_logging(settings.effective_log_level)

logger = logging.getLogger(__name__)
metrics.set_build_info(settings.app_version)


def _active_conversations() -> float:
    try:
        return float(get_conversation_memory().count_active())
    except Exception:  # the gauge is advisory; a failing store must not break /metrics
        return 0.0


metrics.set_active_conversations_source(_active_conversations)


def _route_template(request: Request) -> str | None:
    """The matched route's full path template, e.g. ``/api/v1/schema/tables/{table_name}``.

    Newer FastAPI releases keep included routers nested, and ``scope["route"].path`` is then
    relative to the include prefix (``/schema/tables/{table_name}``). The prefix is recovered
    from the request path so metric labels stay identical across FastAPI versions.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if not template:
        return None
    path = request.scope.get("path") or ""
    path_regex = getattr(route, "path_regex", None)
    segments = [part for part in path.split("/") if part]
    own = [part for part in template.split("/") if part]
    extra = len(segments) - len(own)
    if path_regex is not None and extra > 0:
        prefix = "/" + "/".join(segments[:extra])
        if path_regex.match(path[len(prefix) :]):
            return prefix + template
    return template


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
app.include_router(feedback_router, prefix="/api/v1")
app.include_router(schema_router, prefix="/api/v1")
app.add_api_route("/health", lambda: {"status": "ok"}, methods=["GET"], include_in_schema=False)
app.add_api_route("/health/ready", readiness_check, methods=["GET"], include_in_schema=False)


def metrics_snapshot(request: Request) -> Response:
    """Process-local metrics as JSON. Operator-token protected (see ``authorize_operator``)."""
    denied = authorize_operator(request, settings)
    if denied is not None:
        return denied
    return JSONResponse(metrics.snapshot())


def metrics_prometheus(request: Request) -> Response:
    """The same counters plus labelled histograms in Prometheus text exposition format."""
    denied = authorize_operator(request, settings)
    if denied is not None:
        return denied
    return Response(content=metrics.render_prometheus(), media_type=CONTENT_TYPE_PROMETHEUS)


app.add_api_route("/api/v1/metrics", metrics_snapshot, methods=["GET"], include_in_schema=False)
app.add_api_route(
    "/api/v1/metrics/prometheus", metrics_prometheus, methods=["GET"], include_in_schema=False
)
app.add_middleware(
    RequestSizeLimitMiddleware,
    max_body_bytes=settings.max_request_body_bytes,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
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
        # The route template (never the raw path) keeps metric labels bounded.
        endpoint = _route_template(request)

        elapsed_ms = (perf_counter() - started_at) * 1000
        response.headers["X-Request-ID"] = request_id
        _add_security_headers(response)
        telemetry.conversation_id = telemetry.conversation_id or getattr(
            request.state, "conversation_id", None
        )
        metrics.record_http_request(
            endpoint or "unmatched", request.method, response.status_code, elapsed_ms / 1000
        )
        endpoint = endpoint or path
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
    return error_response(
        status_code,
        code,
        message,
        request_id,
        headers=headers,
        debug=debug,
        include_debug=not settings.is_production,
    )


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
