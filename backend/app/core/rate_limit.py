"""Per-principal rate limiting applied as a route dependency.

Limits run after authentication so they can be keyed on the authenticated principal. Anonymous
(development) requests fall back to the client IP, which is the real client when uvicorn runs
with ``--proxy-headers`` and ``FORWARDED_ALLOW_IPS`` names the trusted proxy.

The counter store is selected by ``RATE_LIMIT_BACKEND``: ``memory`` (per process, the default) or
``redis`` (shared by every replica, so the configured limit holds across the whole deployment).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import Depends, HTTPException, Request, status

from app.core.auth import Principal, get_principal
from app.core.config import Settings, get_settings
from app.core.metrics import metrics
from app.core.middleware import RateLimiter, SlidingWindowRateLimiter
from app.core.redis_limiter import RateLimiterUnavailable, RedisRateLimiter

RateLimitScope = Literal["llm", "conversation", "direct", "read"]


def build_rate_limiter(settings: Settings) -> RateLimiter:
    if settings.rate_limit_backend == "redis" and settings.redis_url is not None:
        return RedisRateLimiter(
            settings.redis_url.get_secret_value(),
            settings.rate_limit_window_seconds,
            requests=settings.rate_limit_requests,
            fail_open=settings.rate_limit_fail_mode == "open",
        )
    return SlidingWindowRateLimiter(
        settings.rate_limit_requests, settings.rate_limit_window_seconds
    )


_settings = get_settings()
rate_limiter: RateLimiter = build_rate_limiter(_settings)


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int, scope: str = "read") -> None:
        super().__init__("rate limit exceeded")
        self.retry_after = retry_after
        self.scope = scope


def rate_limit_key(request: Request, principal: Principal, scope: str) -> str:
    if principal.authenticated:
        identity = f"user:{principal.user_id}"
    else:
        identity = f"ip:{request.client.host if request.client else 'unknown'}"
    return f"{identity}:{scope}"


def enforce_rate_limit(scope: RateLimitScope) -> Callable[..., None]:
    def dependency(
        request: Request,
        principal: Principal = Depends(get_principal),  # noqa: B008
    ) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        limit = (
            settings.effective_llm_rate_limit if scope == "llm" else settings.rate_limit_requests
        )
        try:
            allowed, retry_after = rate_limiter.check(
                rate_limit_key(request, principal, scope), limit=limit
            )
        except RateLimiterUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limiting is temporarily unavailable. Please retry shortly.",
            ) from error
        if not allowed:
            metrics.record_rate_limit_rejection(scope)
            raise RateLimitExceeded(retry_after, scope)

    return dependency
