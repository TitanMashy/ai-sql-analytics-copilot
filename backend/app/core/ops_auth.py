"""Bearer-token protection for operator-only endpoints (metrics, diagnostics).

One ``METRICS_TOKEN`` guards them all. With no token configured the endpoints are open outside
production and disabled (404) in production, so an unconfigured deployment never exposes them.
"""

from __future__ import annotations

import hmac

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import Settings


def error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str | None,
    headers: dict[str, str] | None = None,
    debug: dict | None = None,
    include_debug: bool = False,
) -> JSONResponse:
    error: dict = {"code": code, "message": message, "request_id": request_id}
    if debug and include_debug:
        error["debug"] = debug
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


def authorize_operator(request: Request, settings: Settings) -> JSONResponse | None:
    """Return an error response when the caller may not use operator endpoints, else ``None``."""
    request_id = getattr(request.state, "request_id", None)
    configured = settings.metrics_token.get_secret_value() if settings.metrics_token else ""
    if not configured:
        if settings.is_production:
            return error_response(404, "NOT_FOUND", "Not found.", request_id)
        return None
    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        supplied.strip().encode(), configured.encode()
    ):
        return error_response(
            401,
            "UNAUTHENTICATED",
            "A valid operator token is required.",
            request_id,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return None
