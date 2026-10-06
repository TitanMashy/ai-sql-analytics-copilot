import os

import pytest

from app.core.metrics import metrics
from app.core.redis_limiter import (
    KEY_PREFIX,
    SLIDING_WINDOW_SCRIPT,
    RateLimiterUnavailable,
    RedisRateLimiter,
)
from tests.helpers import require_integration_or_skip


class FakeRedisServer:
    """In-memory stand-in that implements the Lua script's sliding-window semantics.

    Several ``FakeClient`` objects can share one server, which is how two backend replicas share
    one Redis.
    """

    def __init__(self) -> None:
        self.now_ms = 1_000_000
        self.sets: dict[str, list[tuple[int, str]]] = {}
        self.scripts_run = 0

    def run(self, keys: list[str], args: list) -> list[int]:
        self.scripts_run += 1
        window, limit, member = int(args[0]), int(args[1]), str(args[2])
        entries = [item for item in self.sets.get(keys[0], []) if item[0] > self.now_ms - window]
        if len(entries) >= limit:
            oldest = min(score for score, _ in entries)
            retry = max(1, -(-(oldest + window - self.now_ms) // 1000))
            self.sets[keys[0]] = entries
            return [0, retry]
        entries.append((self.now_ms, member))
        self.sets[keys[0]] = entries
        return [1, 0]


class FakeClient:
    def __init__(self, server: FakeRedisServer, down: bool = False) -> None:
        self.server = server
        self.down = down

    def register_script(self, source: str):
        assert source == SLIDING_WINDOW_SCRIPT

        def run(keys: list[str], args: list) -> list[int]:
            if self.down:
                raise ConnectionError("redis is down")
            return self.server.run(keys, args)

        return run

    def ping(self) -> bool:
        if self.down:
            raise ConnectionError("redis is down")
        return True


def _limiter(server: FakeRedisServer, **overrides) -> RedisRateLimiter:
    options = {"url": "redis://unused", "window_seconds": 60, "requests": 3}
    options.update(overrides)
    return RedisRateLimiter(client=FakeClient(server, options.pop("down", False)), **options)


def test_requests_are_counted_per_key_within_the_window() -> None:
    server = FakeRedisServer()
    limiter = _limiter(server)

    results = [limiter.check("user:a:ask") for _ in range(4)]

    assert [allowed for allowed, _ in results] == [True, True, True, False]
    assert results[3][1] >= 1
    assert limiter.check("user:b:ask") == (True, 0)  # another key has its own window


def test_the_window_slides() -> None:
    server = FakeRedisServer()
    limiter = _limiter(server, requests=1)
    assert limiter.check("k") == (True, 0)
    assert limiter.check("k")[0] is False

    server.now_ms += 61_000

    assert limiter.check("k") == (True, 0)


def test_per_call_limit_overrides_the_default() -> None:
    limiter = _limiter(FakeRedisServer(), requests=100)

    assert limiter.check("llm", limit=1) == (True, 0)
    assert limiter.check("llm", limit=1)[0] is False


def test_two_replicas_share_one_combined_limit() -> None:
    server = FakeRedisServer()
    replica_one = _limiter(server, requests=4)
    replica_two = _limiter(server, requests=4)

    outcomes = []
    for index in range(6):
        replica = replica_one if index % 2 == 0 else replica_two
        outcomes.append(replica.check("user:alice:llm")[0])

    # Four admitted across both replicas, the remaining two rejected: the limit is global.
    assert outcomes.count(True) == 4
    assert outcomes.count(False) == 2


def test_keys_are_namespaced() -> None:
    server = FakeRedisServer()
    _limiter(server).check("user:a:ask")

    assert list(server.sets) == [f"{KEY_PREFIX}user:a:ask"]


def test_fail_open_allows_requests_when_redis_is_down() -> None:
    before = metrics.snapshot()["rate_limiter_failures_total"]
    limiter = _limiter(FakeRedisServer(), down=True, fail_open=True)

    assert limiter.check("user:a:ask") == (True, 0)
    assert metrics.snapshot()["rate_limiter_failures_total"] == before + 1


def test_fail_closed_raises_when_redis_is_down() -> None:
    limiter = _limiter(FakeRedisServer(), down=True, fail_open=False)

    with pytest.raises(RateLimiterUnavailable):
        limiter.check("user:a:ask")


def test_ping_reports_latency_and_raises_when_down() -> None:
    assert _limiter(FakeRedisServer()).ping() >= 0
    with pytest.raises(ConnectionError):
        _limiter(FakeRedisServer(), down=True).ping()


def test_script_uses_the_redis_clock() -> None:
    # Replicas with skewed clocks must still agree, so the script reads TIME itself.
    assert "redis.call('TIME')" in SLIDING_WINDOW_SCRIPT


@pytest.mark.integration
def test_real_redis_enforces_one_limit_across_two_replicas() -> None:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        require_integration_or_skip("REDIS_URL is not set")
    from uuid import uuid4

    key = f"integration:{uuid4().hex}"
    replica_one = RedisRateLimiter(url, window_seconds=30, requests=4)
    replica_two = RedisRateLimiter(url, window_seconds=30, requests=4)

    outcomes = [
        (replica_one if index % 2 == 0 else replica_two).check(key)[0] for index in range(6)
    ]

    assert outcomes.count(True) == 4
    assert outcomes.count(False) == 2
    assert replica_one.ping() >= 0


@pytest.mark.integration
def test_real_redis_down_follows_the_fail_mode() -> None:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        require_integration_or_skip("REDIS_URL is not set")
    unreachable = "redis://127.0.0.1:1/0"

    open_limiter = RedisRateLimiter(unreachable, 30, requests=1, fail_open=True)
    closed_limiter = RedisRateLimiter(unreachable, 30, requests=1, fail_open=False)

    assert open_limiter.check("k") == (True, 0)
    with pytest.raises(RateLimiterUnavailable):
        closed_limiter.check("k")
