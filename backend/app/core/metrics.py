from __future__ import annotations

from threading import Lock

COUNTER_NAMES = (
    "analytics_requests_total",
    "successful_analytics_requests_total",
    "failed_analytics_requests_total",
    "validation_failures_total",
    "sql_execution_failures_total",
    "gemini_failures_total",
    "sql_repair_attempts_total",
    "sql_repair_successes_total",
    "rate_limit_responses_total",
)
OBSERVATION_NAMES = (
    "llm_latency_ms",
    "sql_validation_latency_ms",
    "sql_execution_latency_ms",
    "analytics_request_latency_ms",
)


class MetricsRegistry:
    """Small process-local metrics store with bounded names and constant memory use."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters = dict.fromkeys(COUNTER_NAMES, 0)
        self._observations = {name: [0.0, 0] for name in OBSERVATION_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        if name not in self._counters:
            raise ValueError(f"Unknown metric counter: {name}")
        with self._lock:
            self._counters[name] += amount

    def observe(self, name: str, value: float) -> None:
        if name not in self._observations:
            raise ValueError(f"Unknown metric observation: {name}")
        with self._lock:
            observation = self._observations[name]
            observation[0] += max(0.0, value)
            observation[1] += 1

    def record_analytics_request(self, status_code: int, latency_ms: float) -> None:
        self.increment("analytics_requests_total")
        self.increment(
            "successful_analytics_requests_total"
            if status_code < 400
            else "failed_analytics_requests_total"
        )
        self.observe("analytics_request_latency_ms", latency_ms)

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            result: dict[str, int | float] = dict(self._counters)
            for name, (total, count) in self._observations.items():
                result[f"{name}_count"] = count
                result[f"{name}_average"] = round(total / count, 2) if count else 0.0
            return result


metrics = MetricsRegistry()
