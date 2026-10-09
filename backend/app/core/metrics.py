"""Process metrics: a small JSON snapshot plus Prometheus-format counters and histograms.

Every label value is drawn from a bounded set (route templates, HTTP methods and status codes,
provider names, fixed error codes, rate-limit scopes). Question text, SQL, principal ids, and
request ids are never used as labels, so cardinality cannot grow with traffic.
"""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

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
    "deadline_exceeded_total",
    "feedback_total",
)
OBSERVATION_NAMES = (
    "llm_latency_ms",
    "sql_validation_latency_ms",
    "sql_execution_latency_ms",
    "analytics_request_latency_ms",
)

# Seconds. Covers a fast SQL statement (ms) through a slow multi-repair LLM request (tens of s).
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 25.0, 60.0)

CONTENT_TYPE_PROMETHEUS = CONTENT_TYPE_LATEST


def _counter_name(name: str) -> str:
    # prometheus_client appends "_total" to counters itself.
    return "analytics_" + name.removeprefix("analytics_").removesuffix("_total")


def _histogram_name(name: str) -> str:
    return "analytics_" + name.removeprefix("analytics_").removesuffix("_ms") + "_seconds"


class MetricsRegistry:
    """Small process-local metrics store with bounded names and constant memory use."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters = dict.fromkeys(COUNTER_NAMES, 0)
        self._observations = {name: [0.0, 0] for name in OBSERVATION_NAMES}

        self.registry = CollectorRegistry()
        self._prom_counters = {
            name: Counter(_counter_name(name), name.replace("_", " "), registry=self.registry)
            for name in COUNTER_NAMES
        }
        self._prom_histograms = {
            name: Histogram(
                _histogram_name(name),
                name.replace("_", " "),
                buckets=LATENCY_BUCKETS,
                registry=self.registry,
            )
            for name in OBSERVATION_NAMES
        }
        self._http_requests = Counter(
            "analytics_http_requests",
            "HTTP requests by route template, method, and status code",
            ["route", "method", "status"],
            registry=self.registry,
        )
        self._http_duration = Histogram(
            "analytics_http_request_duration_seconds",
            "HTTP request duration by route template and method",
            ["route", "method"],
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self._llm_duration = Histogram(
            "analytics_llm_call_duration_seconds",
            "LLM provider call duration",
            ["provider"],
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self._llm_errors = Counter(
            "analytics_llm_errors",
            "LLM provider failures by provider and error code",
            ["provider", "code"],
            registry=self.registry,
        )
        self._validation_by_reason = Counter(
            "analytics_validation_rejections",
            "SQL rejected by the validator, by error code",
            ["reason"],
            registry=self.registry,
        )
        self._sql_failures_by_code = Counter(
            "analytics_sql_execution_errors",
            "SQL execution failures by error code",
            ["code"],
            registry=self.registry,
        )
        self._rate_limit_by_scope = Counter(
            "analytics_rate_limit_rejections",
            "Requests rejected by the rate limiter, by route family",
            ["scope"],
            registry=self.registry,
        )
        self._feedback = Counter(
            "analytics_feedback_by_rating",
            "User feedback on answers, by rating",
            ["helpful"],
            registry=self.registry,
        )
        self._conversations_active = Gauge(
            "analytics_conversations_active",
            "Conversations active within the retention window",
            registry=self.registry,
        )
        self._build_info = Gauge(
            "analytics_build_info", "Build information", ["version"], registry=self.registry
        )

    # -- core counters and observations ------------------------------------------------------

    def increment(self, name: str, amount: int = 1) -> None:
        if name not in self._counters:
            raise ValueError(f"Unknown metric counter: {name}")
        with self._lock:
            self._counters[name] += amount
        self._prom_counters[name].inc(amount)

    def observe(self, name: str, value: float) -> None:
        if name not in self._observations:
            raise ValueError(f"Unknown metric observation: {name}")
        with self._lock:
            observation = self._observations[name]
            observation[0] += max(0.0, value)
            observation[1] += 1
        self._prom_histograms[name].observe(max(0.0, value) / 1000)

    def record_analytics_request(self, status_code: int, latency_ms: float) -> None:
        self.increment("analytics_requests_total")
        self.increment(
            "successful_analytics_requests_total"
            if status_code < 400
            else "failed_analytics_requests_total"
        )
        self.observe("analytics_request_latency_ms", latency_ms)

    # -- labelled recorders ------------------------------------------------------------------

    def record_http_request(
        self, route: str, method: str, status_code: int, seconds: float
    ) -> None:
        self._http_requests.labels(route, method, str(status_code)).inc()
        self._http_duration.labels(route, method).observe(max(0.0, seconds))

    def record_llm_call(self, provider: str, seconds: float, error_code: str | None = None) -> None:
        self._llm_duration.labels(provider).observe(max(0.0, seconds))
        if error_code:
            self._llm_errors.labels(provider, error_code).inc()

    def record_validation_failure(self, reason: str) -> None:
        self.increment("validation_failures_total")
        self._validation_by_reason.labels(reason).inc()

    def record_sql_failure(self, code: str) -> None:
        self.increment("sql_execution_failures_total")
        self._sql_failures_by_code.labels(code).inc()

    def record_rate_limit_rejection(self, scope: str) -> None:
        self.increment("rate_limit_responses_total")
        self._rate_limit_by_scope.labels(scope).inc()

    def record_feedback(self, helpful: bool) -> None:
        self.increment("feedback_total")
        self._feedback.labels("true" if helpful else "false").inc()

    def set_active_conversations_source(self, source: Callable[[], float]) -> None:
        self._conversations_active.set_function(source)

    def set_build_info(self, version: str) -> None:
        self._build_info.labels(version).set(1)

    # -- exposition --------------------------------------------------------------------------

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            result: dict[str, int | float] = dict(self._counters)
            for name, (total, count) in self._observations.items():
                result[f"{name}_count"] = count
                result[f"{name}_average"] = round(total / count, 2) if count else 0.0
            return result

    def render_prometheus(self) -> bytes:
        return generate_latest(self.registry)


metrics = MetricsRegistry()
