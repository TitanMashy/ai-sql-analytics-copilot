from collections.abc import Generator
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics.dependencies import get_analytics_query_service
from app.analytics.service import AnalyticsQueryService, AnalyticsServiceError
from app.core.config import Settings, get_settings
from app.core.metrics import MetricsRegistry, metrics
from app.core.middleware import SlidingWindowRateLimiter
from app.db.session import _engine_options, get_db
from app.llm.mock_provider import MockLLMProvider
from app.main import app
from app.services.generation import SQLGenerationService
from app.services.llm_dependencies import get_sql_generation_service


@pytest.fixture(autouse=True)
def preserve_dependency_overrides() -> Generator[None, None, None]:
    original = app.dependency_overrides.copy()
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def test_production_settings_mask_secrets_and_disable_debug() -> None:
    settings = Settings(
        environment="production",
        debug=True,
        llm_mode="gemini",
        gemini_api_key=SecretStr("never-log-this-key"),
        database_url="postgresql+psycopg://user:db-password@db/app",
        analytics_database_url="postgresql+psycopg://readonly:other-password@db/app",
        cors_allowed_origins=["https://analytics.example.test"],
    )

    assert settings.is_production
    assert not settings.effective_debug
    assert "never-log-this-key" not in repr(settings)
    assert "db-password" not in repr(settings)
    assert "other-password" not in repr(settings)
    assert settings.cors_allowed_origins == ["https://analytics.example.test"]


def test_production_rejects_sqlite_and_mock_provider() -> None:
    with pytest.raises(ValueError, match="Production requires PostgreSQL"):
        Settings(environment="production", llm_mode="gemini")

    with pytest.raises(ValueError, match="mock provider is disabled"):
        Settings(
            environment="production",
            llm_mode="mock",
            database_url="postgresql+psycopg://app@db/app",
            analytics_database_url="postgresql+psycopg://readonly@db/app",
        )


def test_postgres_pool_options_are_configurable_and_pre_ping() -> None:
    settings = Settings(
        database_pool_size=3,
        database_max_overflow=4,
        database_pool_timeout_seconds=7,
        database_pool_recycle_seconds=900,
        database_connect_timeout_seconds=6,
    )

    options = _engine_options("postgresql+psycopg://user:secret@db/app", settings)

    assert options["pool_size"] == 3
    assert options["max_overflow"] == 4
    assert options["pool_timeout"] == 7
    assert options["pool_recycle"] == 900
    assert options["pool_pre_ping"] is True
    assert options["connect_args"] == {"connect_timeout": 6}


def test_sliding_window_limiter_expires_requests_and_returns_retry_time() -> None:
    limiter = SlidingWindowRateLimiter(requests=2, window_seconds=10)

    assert limiter.check("client", now=1) == (True, 0)
    assert limiter.check("client", now=2) == (True, 0)
    assert limiter.check("client", now=3) == (False, 8)
    assert limiter.check("client", now=12) == (True, 0)


def test_liveness_is_independent_of_database_dependencies() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_middleware_uses_configured_exact_origins() -> None:
    cors = next(item for item in app.user_middleware if item.cls is CORSMiddleware)

    assert cors.kwargs["allow_origins"] == get_settings().cors_allowed_origins
    assert cors.kwargs.get("allow_credentials", False) is False
    assert "X-Request-ID" in cors.kwargs["expose_headers"]


def test_readiness_checks_application_and_analytics_databases() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session = sessionmaker(bind=engine)

    def override_database() -> Generator:
        with test_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_database
    app.dependency_overrides[get_analytics_query_service] = lambda: AnalyticsQueryService(engine)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_returns_sanitized_503_when_analytics_database_is_down() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    test_session = sessionmaker(bind=engine)

    def override_database() -> Generator:
        with test_session() as session:
            yield session

    class UnavailableEngine:
        dialect = SimpleNamespace(name="postgresql")

        @contextmanager
        def connect(self):
            raise SQLAlchemyError("postgres://user:secret@db/app")
            yield

    app.dependency_overrides[get_db] = override_database
    app.dependency_overrides[get_analytics_query_service] = lambda: AnalyticsQueryService(
        UnavailableEngine()  # type: ignore[arg-type]
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "A required database dependency is unavailable."
    assert "secret" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_question_length_and_malformed_json_return_correlated_errors() -> None:
    with TestClient(app) as client:
        oversized_question = client.post(
            "/api/v1/analytics/generate",
            json={"question": "x" * 2001},
        )
        malformed_json = client.post(
            "/api/v1/analytics/generate",
            content="{",
            headers={"Content-Type": "application/json"},
        )
        oversized_context = client.post(
            "/api/v1/analytics/generate",
            json={"question": "Summarize", "conversation_context": "x" * 2001},
        )
        oversized_turn = client.post(
            "/api/v1/analytics/conversations/test-session/turns",
            json={"role": "user", "content": "x" * 2001},
        )

    for response in (oversized_question, malformed_json, oversized_context, oversized_turn):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_REQUEST"
        assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_oversized_body_is_rejected_before_json_parsing() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/analytics/generate",
            json={"question": "x" * 17000},
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_expensive_endpoint_is_rate_limited_with_retry_after(monkeypatch) -> None:
    original_limiter = __import__("app.main", fromlist=["rate_limiter"]).rate_limiter
    monkeypatch.setattr(
        "app.main.rate_limiter", SlidingWindowRateLimiter(requests=1, window_seconds=30)
    )
    app.dependency_overrides[get_sql_generation_service] = lambda: SQLGenerationService(
        MockLLMProvider()
    )
    before = metrics.snapshot()["rate_limit_responses_total"]

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/analytics/generate",
            json={"question": "How many active vehicles do we have?"},
        )
        limited = client.post(
            "/api/v1/analytics/generate",
            json={"question": "How many active vehicles do we have?"},
        )

    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["Retry-After"]
    assert limited.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert metrics.snapshot()["rate_limit_responses_total"] == before + 1
    monkeypatch.setattr("app.main.rate_limiter", original_limiter)


def test_metrics_snapshot_has_required_counters_and_latency_averages() -> None:
    registry = MetricsRegistry()
    registry.record_analytics_request(200, 10)
    registry.record_analytics_request(503, 30)
    registry.increment("gemini_failures_total")
    registry.observe("llm_latency_ms", 20)

    snapshot = registry.snapshot()

    assert snapshot["analytics_requests_total"] == 2
    assert snapshot["successful_analytics_requests_total"] == 1
    assert snapshot["failed_analytics_requests_total"] == 1
    assert snapshot["gemini_failures_total"] == 1
    assert snapshot["llm_latency_ms_average"] == 20
    assert "sql_execution_failures_total" in snapshot


def test_metrics_api_exposes_process_counters_and_latency_averages() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/metrics")

    assert response.status_code == 200
    assert "analytics_requests_total" in response.json()
    assert "llm_latency_ms_average" in response.json()
    assert "sql_execution_failures_total" in response.json()


def test_missing_conversation_uses_conversation_error_code() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/analytics/conversations/missing-session")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_status"),
    [
        (
            SQLAlchemyTimeoutError("pool checkout timeout"),
            "DATABASE_POOL_TIMEOUT",
            503,
        ),
        (
            OperationalError("connect", {}, RuntimeError("connection refused")),
            "DATABASE_UNAVAILABLE",
            503,
        ),
        (
            OperationalError("execute", {}, RuntimeError("statement timeout")),
            "QUERY_TIMEOUT",
            408,
        ),
    ],
)
def test_database_failures_are_classified_without_leaking_details(
    failure: SQLAlchemyError, expected_code: str, expected_status: int
) -> None:
    class FailingEngine:
        dialect = SimpleNamespace(name="postgresql")

        @contextmanager
        def connect(self):
            raise failure
            yield

    service = AnalyticsQueryService(FailingEngine())  # type: ignore[arg-type]

    with pytest.raises(AnalyticsServiceError) as error:
        service.execute("SELECT COUNT(*) FROM vehicles")

    assert error.value.code == expected_code
    assert error.value.status_code == expected_status
    assert "connection refused" not in error.value.message
    assert "statement timeout" not in error.value.message


def test_unexpected_exception_response_does_not_leak_exception_text() -> None:
    async def raise_secret_error() -> None:
        raise RuntimeError("postgres://user:private-password@database/app")

    app.add_api_route("/__test/production-error", raise_secret_error, methods=["GET"])
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/__test/production-error")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.json()["error"]["message"] == "The request could not be completed."
    assert "private-password" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
