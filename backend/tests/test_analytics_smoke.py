from collections.abc import Generator
from time import perf_counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import StaticPool

from app.analytics.dependencies import get_analytics_query_service
from app.analytics.service import AnalyticsQueryService
from app.main import app

SMOKE_QUERIES = [
    (
        "active_vehicle_count",
        "SELECT COUNT(*) AS active_vehicle_count FROM vehicles WHERE status = 'active'",
    ),
    (
        "total_revenue",
        "SELECT SUM(total_amount) AS total_revenue FROM invoices WHERE status <> 'cancelled'",
    ),
    (
        "top_customers",
        "SELECT c.company_name, SUM(i.total_amount) AS total_revenue "
        "FROM customers c JOIN invoices i ON i.customer_id = c.id "
        "WHERE i.status <> 'cancelled' GROUP BY c.id, c.company_name "
        "ORDER BY total_revenue DESC LIMIT 10",
    ),
    (
        "monthly_revenue",
        "SELECT to_char(invoice_date, 'YYYY-MM') AS revenue_month, "
        "SUM(total_amount) AS total_revenue FROM invoices "
        "WHERE status <> 'cancelled' GROUP BY revenue_month ORDER BY revenue_month",
    ),
    (
        "vehicle_idle_time",
        "SELECT v.registration_number, AVG(t.idle_time_minutes) AS average_idle_minutes "
        "FROM vehicles v JOIN trips t ON t.vehicle_id = v.id "
        "GROUP BY v.id, v.registration_number ORDER BY average_idle_minutes DESC LIMIT 10",
    ),
    (
        "fuel_consumption",
        "SELECT v.registration_number, SUM(f.liters) AS total_liters, "
        "SUM(f.total_cost) AS total_fuel_cost FROM vehicles v "
        "JOIN fuel_records f ON f.vehicle_id = v.id "
        "GROUP BY v.id, v.registration_number ORDER BY total_liters DESC LIMIT 10",
    ),
]


@pytest.fixture
def smoke_client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def add_postgres_date_format(dbapi_connection, connection_record) -> None:
        del connection_record
        dbapi_connection.create_function("to_char", 2, lambda value, _format: str(value)[:7])

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE customers (id INTEGER, company_name TEXT)"))
        connection.execute(
            text("CREATE TABLE vehicles (id INTEGER, status TEXT, registration_number TEXT)")
        )
        connection.execute(
            text(
                "CREATE TABLE invoices (id INTEGER, customer_id INTEGER, total_amount REAL, "
                "status TEXT, invoice_date TEXT)"
            )
        )
        connection.execute(
            text("CREATE TABLE trips (id INTEGER, vehicle_id INTEGER, idle_time_minutes REAL)")
        )
        connection.execute(
            text(
                "CREATE TABLE fuel_records (id INTEGER, vehicle_id INTEGER, "
                "liters REAL, total_cost REAL)"
            )
        )
        connection.execute(text("INSERT INTO customers VALUES (1, 'Northstar'), (2, 'Harbor')"))
        connection.execute(
            text(
                "INSERT INTO vehicles VALUES (1, 'active', 'FLEET-1'), "
                "(2, 'active', 'FLEET-2'), (3, 'retired', 'FLEET-3')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO invoices VALUES "
                "(1, 1, 1000, 'paid', '2026-01-15'), "
                "(2, 1, 500, 'paid', '2026-02-15'), "
                "(3, 2, 750, 'paid', '2026-02-20'), "
                "(4, 2, 250, 'cancelled', '2026-02-21')"
            )
        )
        connection.execute(text("INSERT INTO trips VALUES (1, 1, 20), (2, 1, 40), (3, 2, 15)"))
        connection.execute(
            text("INSERT INTO fuel_records VALUES (1, 1, 100, 150), (2, 2, 80, 120)")
        )

    service = AnalyticsQueryService(engine)
    app.dependency_overrides[get_analytics_query_service] = lambda: service
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_analytics_query_service, None)
    engine.dispose()


def test_representative_analytics_smoke_and_latency(
    smoke_client: TestClient, record_property
) -> None:
    for name, sql in SMOKE_QUERIES:
        started_at = perf_counter()
        response = smoke_client.post("/api/v1/analytics/query", json={"sql": sql})
        total_api_ms = (perf_counter() - started_at) * 1000

        assert response.status_code == 200, (name, response.text)
        body = response.json()
        assert body["row_count"] > 0, name
        assert body["execution_time_ms"] >= 0, name
        assert total_api_ms < 5000, (name, total_api_ms)
        record_property(f"{name}_sql_execution_ms", body["execution_time_ms"])
        record_property(f"{name}_total_api_ms", round(total_api_ms, 2))
