from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.analytics.dependencies import get_analytics_query_service
from app.analytics.serialization import normalize_value
from app.analytics.service import AnalyticsQueryService
from app.main import app


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE vehicles (id INTEGER, status TEXT, amount NUMERIC)"))
        connection.execute(
            text(
                "INSERT INTO vehicles (id, status, amount) VALUES "
                "(1, 'active', 12.50), (2, 'inactive', 20.25), (3, 'active', 30.00)"
            )
        )

    service = AnalyticsQueryService(engine, max_result_rows=2)
    app.dependency_overrides[get_analytics_query_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_valid_query_returns_rows_and_timing(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analytics/query",
        json={"sql": "SELECT COUNT(*) AS vehicle_count FROM vehicles"},
    )

    assert response.status_code == 200
    assert response.json()["columns"] == ["vehicle_count"]
    assert response.json()["rows"] == [{"vehicle_count": 3}]
    assert response.json()["row_count"] == 1
    assert response.json()["execution_time_ms"] >= 0
    assert response.headers["X-Request-ID"]


def test_validation_endpoint_accepts_select_and_warns(client: TestClient) -> None:
    response = client.post("/api/v1/analytics/validate", json={"sql": "SELECT * FROM vehicles"})

    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["errors"] == []
    assert response.json()["warnings"]


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("", "SQL query cannot be empty."),
        ("UPDATE vehicles SET status = 'retired'", "Only SELECT statements are permitted."),
        ("SELECT 1; SELECT 2", "Multiple SQL statements are not permitted."),
    ],
)
def test_invalid_sql_returns_structured_error(client: TestClient, sql: str, message: str) -> None:
    response = client.post("/api/v1/analytics/query", json={"sql": sql})

    assert response.status_code == 400
    if sql.startswith("UPDATE") or ";" in sql:
        assert response.json()["error"]["code"] == "QUERY_SECURITY_ERROR"
    else:
        assert response.json()["error"]["code"] == "QUERY_VALIDATION_ERROR"
    assert message in response.json()["error"]["message"]


def test_nonexistent_table_returns_table_error(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analytics/query",
        json={"sql": "SELECT * FROM does_not_exist"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "TABLE_NOT_FOUND", "message": "The requested table does not exist."}
    }


def test_system_table_returns_security_error(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analytics/query",
        json={"sql": "SELECT * FROM pg_catalog.pg_tables"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "QUERY_SECURITY_ERROR"


def test_database_error_is_structured(client: TestClient) -> None:
    response = client.post("/api/v1/analytics/query", json={"sql": "SELECT * FROM"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "QUERY_PARSE_ERROR"


def test_row_limit_is_enforced(client: TestClient) -> None:
    response = client.post("/api/v1/analytics/query", json={"sql": "SELECT id FROM vehicles"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "RESULT_LIMIT_EXCEEDED"


def test_result_values_are_json_safe() -> None:
    assert normalize_value(Decimal("10.25")) == 10.25
    assert normalize_value(datetime(2025, 1, 1, tzinfo=UTC)) == "2025-01-01T00:00:00+00:00"
    assert (
        normalize_value(UUID("12345678-1234-5678-1234-567812345678"))
        == "12345678-1234-5678-1234-567812345678"
    )


def test_schema_endpoints_and_docs(client: TestClient) -> None:
    tables_response = client.get("/api/v1/schema/tables")
    table_response = client.get("/api/v1/schema/tables/vehicles")
    invalid_response = client.get("/api/v1/schema/tables/not_a_table")
    docs_response = client.get("/docs")

    assert tables_response.status_code == 200
    assert "vehicles" in tables_response.json()["tables"]
    assert table_response.status_code == 200
    assert table_response.json()["name"] == "vehicles"
    assert invalid_response.status_code == 404
    assert invalid_response.json()["error"]["code"] == "TABLE_NOT_FOUND"
    assert docs_response.status_code == 200
