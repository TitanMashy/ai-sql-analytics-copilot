"""Per-principal rate limiting applied as a route dependency.

Limits run after authentication so they can be keyed on the authenticated principal. Anonymous
(development) requests fall back to the client IP, which is the real client when uvicorn runs
with ``--proxy-headers`` and ``FORWARDED_ALLOW_IPS`` names the trusted proxy.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import Depends, Request

from app.core.auth import Principal, get_principal
from app.core.config import get_settings
from app.core.metrics import metrics
from app.core.middleware import SlidingWindowRateLimiter

RateLimitScope = Literal["llm", "conversation", "direct", "read"]

_settings = get_settings()
rate_limiter = SlidingWindowRateLimiter(
    _settings.rate_limit_requests, _settings.rate_limit_window_seconds
)


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("rate limit exceeded")
        self.retry_after = retry_after


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
        allowed, retry_after = rate_limiter.check(
            rate_limit_key(request, principal, scope), limit=limit
        )
        if not allowed:
            metrics.increment("rate_limit_responses_total")
            raise RateLimitExceeded(retry_after)

    return dependency
