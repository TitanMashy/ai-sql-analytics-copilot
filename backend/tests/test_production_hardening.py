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
from app.core.auth import Principal
from app.core.config import Settings, get_settings
from app.core.metrics import MetricsRegistry, metrics
from app.core.middleware import SlidingWindowRateLimiter
from app.core.rate_limit import rate_limit_key
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
        auth_mode="jwt",
        jwt_algorithm="HS256",
        jwt_secret=SecretStr("jwt-secret-that-must-never-be-logged-0123456789"),
        jwt_issuer="https://issuer.example.test",
        jwt_audience="analytics-api",
        metrics_token=SecretStr("metrics-token-value"),
    )

    assert settings.is_production
    assert not settings.effective_debug
    assert not settings.direct_sql_endpoints_enabled
    assert "never-log-this-key" not in repr(settings)
    assert "jwt-secret-that-must-never-be-logged" not in repr(settings)
    assert "metrics-token-value" not in repr(settings)
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


def _production_kwargs(**overrides):
    values = {
        "environment": "production",
        "llm_mode": "gemini",
        "gemini_api_key": SecretStr("key"),
        "database_url": "postgresql+psycopg://app@db/app",
        "analytics_database_url": "postgresql+psycopg://readonly@db/app",
    }
    values.update(overrides)
    return values


def test_production_requires_signed_token_authentication() -> None:
    with pytest.raises(ValueError, match="AUTH_MODE=jwt"):
        Settings(**_production_kwargs(auth_mode="disabled"))


def test_jwt_configuration_must_be_complete() -> None:
    with pytest.raises(ValueError, match="JWT_ISSUER and JWT_AUDIENCE"):
        Settings(**_production_kwargs(auth_mode="jwt", jwt_public_key="pem"))
    with pytest.raises(ValueError, match="JWT_PUBLIC_KEY"):
        Settings(
            **_production_kwargs(
                auth_mode="jwt", jwt_issuer="https://issuer", jwt_audience="analytics"
            )
        )
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(
            auth_mode="jwt",
            jwt_algorithm="HS256",
            jwt_secret="too-short",
            jwt_issuer="https://issuer",
            jwt_audience="analytics",
        )


def test_direct_sql_endpoints_are_off_in_production_unless_enabled() -> None:
    auth = {
        "auth_mode": "jwt",
        "jwt_algorithm": "HS256",
        "jwt_secret": "s" * 32,
        "jwt_issuer": "https://issuer",
        "jwt_audience": "analytics",
    }

    assert Settings().direct_sql_endpoints_enabled
    assert not Settings(**_production_kwargs(**auth)).direct_sql_endpoints_enabled
    assert Settings(
        **_production_kwargs(enable_direct_sql_endpoints=True, **auth)
    ).direct_sql_endpoints_enabled
    assert not Settings(enable_direct_sql_endpoints=False).direct_sql_endpoints_enabled


def test_llm_rate_limit_is_stricter_than_the_general_limit_by_default() -> None:
    assert Settings(rate_limit_requests=60).effective_llm_rate_limit == 20
    assert Settings(rate_limit_requests=5).effective_llm_rate_limit == 5
    assert Settings(rate_limit_requests=60, rate_limit_llm_requests=7).effective_llm_rate_limit == 7


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


def test_limiter_accepts_a_per_call_limit_override() -> None:
    limiter = SlidingWindowRateLimiter(requests=100, window_seconds=10)

    assert limiter.check("llm", now=1, limit=1) == (True, 0)
    assert limiter.check("llm", now=2, limit=1) == (False, 9)
    assert limiter.check("other", now=2) == (True, 0)


def test_rate_limit_keys_isolate_principals_behind_one_proxy_address() -> None:
    request = SimpleNamespace(client=SimpleNamespace(host="10.0.0.5"))
    alice = Principal("alice", customer_id=1)
    bob = Principal("bob", customer_id=2)
    anonymous = Principal("development-anonymous", authenticated=False)

    assert rate_limit_key(request, alice, "llm") != rate_limit_key(request, bob, "llm")
    assert rate_limit_key(request, alice, "llm") != rate_limit_key(request, alice, "read")
    assert rate_limit_key(request, anonymous, "llm") == "ip:10.0.0.5:llm"


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


@pytest.fixture
def strict_rate_limits(monkeypatch) -> None:
    """One request per window for every scope, with a fresh limiter for each test."""
    monkeypatch.setattr(
        "app.core.rate_limit.get_settings",
        lambda: Settings(rate_limit_requests=1, rate_limit_llm_requests=1),
    )
    monkeypatch.setattr(
        "app.core.rate_limit.rate_limiter",
        SlidingWindowRateLimiter(requests=100, window_seconds=30),
    )


def test_expensive_endpoint_is_rate_limited_with_retry_after(strict_rate_limits) -> None:
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


def test_one_principal_exhausting_its_quota_does_not_limit_another(strict_rate_limits) -> None:
    from app.core.auth import get_principal

    current = {"principal": Principal("alice", customer_id=1)}
    app.dependency_overrides[get_principal] = lambda: current["principal"]
    app.dependency_overrides[get_sql_generation_service] = lambda: SQLGenerationService(
        MockLLMProvider()
    )
    body = {"question": "How many active vehicles do we have?"}

    with TestClient(app) as client:
        alice_first = client.post("/api/v1/analytics/generate", json=body)
        alice_second = client.post("/api/v1/analytics/generate", json=body)
        current["principal"] = Principal("bob", customer_id=2)
        bob_first = client.post("/api/v1/analytics/generate", json=body)

    assert alice_first.status_code == 200
    assert alice_second.status_code == 429
    assert bob_first.status_code == 200


def test_every_analytics_route_family_is_rate_limited(strict_rate_limits) -> None:
    with TestClient(app) as client:
        schema_first = client.get("/api/v1/schema/tables")
        schema_second = client.get("/api/v1/schema/tables")
        create_first = client.post("/api/v1/analytics/conversations")
        create_second = client.post("/api/v1/analytics/conversations")

    assert schema_first.status_code == 200
    assert schema_second.status_code == 429
    assert create_first.status_code == 200
    assert create_second.status_code == 429


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


def test_metrics_api_exposes_process_counters_when_no_token_is_configured() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/metrics")

    assert response.status_code == 200
    assert "analytics_requests_total" in response.json()
    assert "llm_latency_ms_average" in response.json()
    assert "sql_execution_failures_total" in response.json()


def test_metrics_require_the_bearer_token_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.main.settings", Settings(metrics_token=SecretStr("metrics-secret-value"))
    )
    with TestClient(app) as client:
        missing = client.get("/api/v1/metrics")
        wrong = client.get("/api/v1/metrics", headers={"Authorization": "Bearer nope"})
        correct = client.get(
            "/api/v1/metrics", headers={"Authorization": "Bearer metrics-secret-value"}
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "UNAUTHENTICATED"
    assert wrong.status_code == 401
    assert correct.status_code == 200
    assert "analytics_requests_total" in correct.json()


def test_metrics_are_disabled_in_production_without_a_token(monkeypatch) -> None:
    production = Settings(
        **_production_kwargs(
            auth_mode="jwt",
            jwt_algorithm="HS256",
            jwt_secret="s" * 32,
            jwt_issuer="https://issuer",
            jwt_audience="analytics",
        )
    )
    monkeypatch.setattr("app.main.settings", production)
    with TestClient(app) as client:
        response = client.get("/api/v1/metrics")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_direct_sql_routes_are_mounted_when_enabled_in_this_environment() -> None:
    # The OpenAPI document lists every mounted path; ``app.routes`` keeps included routers nested
    # in newer FastAPI releases and no longer lists them flat.
    paths = set(app.openapi()["paths"])

    assert get_settings().direct_sql_endpoints_enabled
    assert "/api/v1/analytics/query" in paths
    assert "/api/v1/analytics/validate" in paths
    assert "/api/v1/analytics/ask" in paths


def test_unknown_routes_use_the_error_envelope() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/not-a-route")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


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
