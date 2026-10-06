from collections.abc import Generator
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics.dependencies import get_analytics_query_service
from app.analytics.service import AnalyticsQueryService
from app.conversation.service import get_conversation_memory
from app.core import rate_limit
from app.core.auth import Principal, get_principal
from app.core.config import Settings
from app.db.operational import OperationalBase
from app.db.seed import ProductionSeedError, seed_database
from app.db.session import get_db
from app.jobs.purge import run_purge
from app.main import app


@pytest.fixture(autouse=True)
def restore_overrides() -> Generator[None, None, None]:
    original = app.dependency_overrides.copy()
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


@pytest.fixture
def healthy_databases() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    factory = sessionmaker(bind=engine)

    def override_database() -> Generator:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_database
    app.dependency_overrides[get_analytics_query_service] = lambda: AnalyticsQueryService(engine)


# -- readiness semantics --------------------------------------------------------------------


def test_readiness_is_ready_when_everything_is_available(healthy_databases) -> None:
    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_missing_llm_key_reports_degraded_with_http_200(healthy_databases, monkeypatch) -> None:
    monkeypatch.setattr("app.api.health.get_settings", lambda: Settings(llm_mode="gemini"))

    with TestClient(app) as client:
        response = client.get("/health/ready")

    # The container stays in service: restarting it would not fix a missing key.
    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "degraded": ["llm_provider"]}


class DownLimiter:
    def check(self, key, now=None, limit=None):
        return True, 0

    def ping(self):
        raise ConnectionError("redis is down")


def test_redis_down_while_failing_open_is_degraded_not_unready(
    healthy_databases, monkeypatch
) -> None:
    monkeypatch.setattr(rate_limit, "rate_limiter", DownLimiter())
    monkeypatch.setattr(
        "app.api.health.get_settings",
        lambda: Settings(
            rate_limit_backend="redis", redis_url="redis://cache", rate_limit_fail_mode="open"
        ),
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "degraded": ["rate_limiter"]}


def test_redis_down_while_failing_closed_makes_the_instance_unready(
    healthy_databases, monkeypatch
) -> None:
    monkeypatch.setattr(rate_limit, "rate_limiter", DownLimiter())
    monkeypatch.setattr(
        "app.api.health.get_settings",
        lambda: Settings(
            rate_limit_backend="redis", redis_url="redis://cache", rate_limit_fail_mode="closed"
        ),
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "redis" not in response.text.lower()


def test_required_database_down_is_unready_and_sanitized() -> None:
    class UnavailableEngine:
        dialect = SimpleNamespace(name="postgresql")

        @contextmanager
        def connect(self):
            raise SQLAlchemyError("postgres://user:secret@db/app")
            yield

    engine = create_engine("sqlite://", poolclass=StaticPool)
    factory = sessionmaker(bind=engine)

    def override_database() -> Generator:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_database
    app.dependency_overrides[get_analytics_query_service] = lambda: AnalyticsQueryService(
        UnavailableEngine()  # type: ignore[arg-type]
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert "secret" not in response.text


def test_liveness_never_touches_dependencies() -> None:
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_unready_and_degraded_do_not_change_liveness(healthy_databases, monkeypatch) -> None:
    monkeypatch.setattr("app.api.health.get_settings", lambda: Settings(llm_mode="gemini"))

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


# -- diagnostics ----------------------------------------------------------------------------


def test_diagnostics_require_the_operator_token(healthy_databases, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.health.get_settings",
        lambda: Settings(metrics_token=SecretStr("operator-token-value")),
    )

    with TestClient(app) as client:
        missing = client.get("/api/v1/health/diagnostics")
        allowed = client.get(
            "/api/v1/health/diagnostics",
            headers={"Authorization": "Bearer operator-token-value"},
        )

    assert missing.status_code == 401
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["checks"]["application_database"]["ok"] is True
    assert body["checks"]["analytics_database"]["ok"] is True
    assert body["features"]["conversation_store"] == "memory"
    assert body["features"]["sql_cache_enabled"] is False
    assert "operator-token-value" not in allowed.text
    assert "sqlite" not in allowed.text.lower()  # no connection URLs


def test_diagnostics_are_disabled_in_production_without_a_token(
    healthy_databases, monkeypatch
) -> None:
    production = Settings.model_construct(
        environment="production", metrics_token=None, llm_mode="gemini", app_version="1.0.0"
    )
    monkeypatch.setattr("app.api.health.get_settings", lambda: production)

    with TestClient(app) as client:
        response = client.get("/api/v1/health/diagnostics")

    assert response.status_code == 404


# -- conversations: delete, business definitions --------------------------------------------


def test_a_conversation_can_be_deleted_only_by_its_owner() -> None:
    current = {"principal": Principal("alice", customer_id=1)}
    app.dependency_overrides[get_principal] = lambda: current["principal"]

    with TestClient(app) as client:
        conversation_id = client.post("/api/v1/analytics/conversations").json()["conversation_id"]
        current["principal"] = Principal("bob", customer_id=2)
        by_bob = client.delete(f"/api/v1/analytics/conversations/{conversation_id}")
        current["principal"] = Principal("alice", customer_id=1)
        by_alice = client.delete(f"/api/v1/analytics/conversations/{conversation_id}")
        again = client.delete(f"/api/v1/analytics/conversations/{conversation_id}")
        gone = client.get(f"/api/v1/analytics/conversations/{conversation_id}")

    assert by_bob.status_code == 404
    assert by_bob.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert by_alice.status_code == 204
    assert by_alice.content == b""
    assert again.status_code == 404
    assert gone.status_code == 404


def test_business_definitions_and_example_questions_are_served() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/schema/business-definitions")

    body = response.json()
    assert response.status_code == 200
    names = {item["name"] for item in body["definitions"]}
    assert {"revenue", "active vehicle", "idle time"} <= names
    assert all(item["definition"] for item in body["definitions"])
    assert "How many active vehicles do we have?" in body["examples"]


# -- seed guard and retention job -----------------------------------------------------------


def test_the_demo_seed_refuses_to_run_in_production(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.db.seed.get_settings", lambda: Settings.model_construct(environment="production")
    )

    with pytest.raises(ProductionSeedError):
        seed_database(session=None)  # type: ignore[arg-type]


def test_the_seed_cli_exits_with_a_clear_message_in_production(monkeypatch) -> None:
    from app.db import seed

    monkeypatch.setattr(
        "app.db.seed.get_settings", lambda: Settings.model_construct(environment="production")
    )
    monkeypatch.setattr("sys.argv", ["seed"])

    with pytest.raises(SystemExit) as error:
        seed.main()

    assert "Refusing to load demo data" in str(error.value)


def test_purge_job_reports_counts_and_is_idempotent() -> None:
    get_conversation_memory.cache_clear()
    try:
        first = run_purge()
        second = run_purge()
    finally:
        get_conversation_memory.cache_clear()

    assert set(first) == {"conversations_purged", "audit_records_purged"}
    assert second["conversations_purged"] == 0


def test_operational_tables_are_not_part_of_the_analytics_surface() -> None:
    from app.analytics.validator import ALLOWED_TABLES
    from app.db.base import Base

    operational = set(OperationalBase.metadata.tables)

    assert {"conversations", "conversation_turns", "audit_log"} <= operational
    assert operational.isdisjoint(ALLOWED_TABLES)
    assert operational.isdisjoint(set(Base.metadata.tables))
