"""Redis-backed sliding-window rate limiter shared by every backend replica.

Selected with ``RATE_LIMIT_BACKEND=redis``. Each key is a sorted set of request timestamps; one Lua
script trims the window, counts, and records the request atomically, using Redis's own clock so
replicas with skewed clocks still agree. If Redis is unreachable the limiter either allows the
request (``RATE_LIMIT_FAIL_MODE=open``, the default: availability over strictness) or raises
:class:`RateLimiterUnavailable` (``closed``: strictness over availability).
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import uuid4

from app.core.metrics import metrics

logger = logging.getLogger(__name__)

KEY_PREFIX = "analytics:ratelimit:"

# KEYS[1] = sorted set; ARGV = window (ms), limit, unique member.
# Returns {allowed (1/0), retry_after_seconds}.
SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local member = ARGV[3]
local time = redis.call('TIME')
local now = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry = math.ceil((tonumber(oldest[2]) + window - now) / 1000)
  if retry < 1 then retry = 1 end
  return {0, retry}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window)
return {1, 0}
"""


class RateLimiterUnavailable(Exception):
    """Redis could not be reached and the limiter is configured to fail closed."""


class RedisRateLimiter:
    def __init__(
        self,
        url: str,
        window_seconds: int,
        requests: int = 30,
        fail_open: bool = True,
        client: Any | None = None,
        socket_timeout: float = 0.25,
    ) -> None:
        self.requests = requests
        self.window_seconds = window_seconds
        self.fail_open = fail_open
        if client is None:
            import redis  # imported lazily so the memory backend never needs the package

            client = redis.Redis.from_url(
                url,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_timeout,
                health_check_interval=30,
            )
        self._client = client
        self._script = client.register_script(SLIDING_WINDOW_SCRIPT)

    def check(
        self, key: str, now: float | None = None, limit: int | None = None
    ) -> tuple[bool, int]:
        del now  # Redis supplies the clock
        allowed_requests = self.requests if limit is None else limit
        try:
            allowed, retry_after = self._script(
                keys=[f"{KEY_PREFIX}{key}"],
                args=[self.window_seconds * 1000, allowed_requests, uuid4().hex],
            )
        except Exception as error:  # redis.RedisError subclasses, plus socket-level failures
            metrics.increment("rate_limiter_failures_total")
            logger.warning(
                "rate limiter backend unavailable",
                extra={"error_type": type(error).__name__},
            )
            if self.fail_open:
                return True, 0
            raise RateLimiterUnavailable from error
        return bool(int(allowed)), int(retry_after)

    def ping(self) -> float:
        """Round-trip time in seconds; raises if Redis is unreachable. Used by readiness."""
        started_at = time.perf_counter()
        self._client.ping()
        return time.perf_counter() - started_at
