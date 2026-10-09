import logging
import re

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics.service import AnalyticsQueryService
from app.core.audit import (
    AuditEvent,
    AuditService,
    DatabaseAuditSink,
    LogAuditSink,
    hash_sql,
    purge_audit_records,
)
from app.core.config import Settings
from app.core.metrics import MetricsRegistry
from app.db.operational import AuditRecord, OperationalBase
from app.llm.mock_provider import MockLLMProvider
from app.main import app
from app.services.generation import SQLGenerationService
from app.services.llm_dependencies import get_sql_generation_service

QUESTION = "How many active vehicles do we have?"


# -- Prometheus metrics ---------------------------------------------------------------------


def _exposition(registry: MetricsRegistry) -> str:
    return registry.render_prometheus().decode()


def test_exposition_contains_counters_histograms_and_build_info() -> None:
    registry = MetricsRegistry()
    registry.set_build_info("1.2.3")
    registry.record_http_request("/api/v1/analytics/ask", "POST", 200, 0.42)
    registry.record_llm_call("gemini", 1.5, "LLM_TIMEOUT")
    registry.record_validation_failure("QUERY_SECURITY_ERROR")
    registry.record_sql_failure("COLUMN_NOT_FOUND")
    registry.record_rate_limit_rejection("llm")
    registry.increment("sql_repair_attempts_total")
    registry.increment("sql_repair_successes_total")
    registry.observe("sql_execution_latency_ms", 120)
    registry.record_feedback(False)

    text = _exposition(registry)

    assert 'analytics_build_info{version="1.2.3"} 1.0' in text
    assert (
        "analytics_http_requests_total"
        '{method="POST",route="/api/v1/analytics/ask",status="200"} 1.0'
    ) in text
    assert "analytics_http_request_duration_seconds_bucket" in text
    assert 'analytics_llm_errors_total{code="LLM_TIMEOUT",provider="gemini"} 1.0' in text
    assert 'analytics_validation_rejections_total{reason="QUERY_SECURITY_ERROR"} 1.0' in text
    assert 'analytics_sql_execution_errors_total{code="COLUMN_NOT_FOUND"} 1.0' in text
    assert 'analytics_rate_limit_rejections_total{scope="llm"} 1.0' in text
    assert "analytics_sql_repair_attempts_total 1.0" in text
    assert "analytics_sql_execution_latency_seconds_bucket" in text
    assert 'analytics_feedback_by_rating_total{helpful="false"} 1.0' in text


def test_labelled_recorders_also_feed_the_json_counters() -> None:
    registry = MetricsRegistry()
    registry.record_validation_failure("QUERY_PARSE_ERROR")
    registry.record_sql_failure("QUERY_TIMEOUT")
    registry.record_rate_limit_rejection("read")
    registry.record_feedback(True)

    snapshot = registry.snapshot()

    assert snapshot["validation_failures_total"] == 1
    assert snapshot["sql_execution_failures_total"] == 1
    assert snapshot["rate_limit_responses_total"] == 1
    assert snapshot["feedback_total"] == 1


def test_active_conversations_gauge_reads_its_source_lazily() -> None:
    registry = MetricsRegistry()
    value = {"count": 3.0}
    registry.set_active_conversations_source(lambda: value["count"])

    assert "analytics_conversations_active 3.0" in _exposition(registry)
    value["count"] = 7.0
    assert "analytics_conversations_active 7.0" in _exposition(registry)


def test_label_values_never_contain_question_or_sql_text() -> None:
    registry = MetricsRegistry()
    registry.record_http_request("/api/v1/analytics/ask", "POST", 200, 0.1)
    registry.record_validation_failure("QUERY_SECURITY_ERROR")

    text = _exposition(registry)

    assert "SELECT" not in text
    assert QUESTION not in text
    assert not re.search(r'="[^"]{80,}"', text)  # no long free-text label values


def test_prometheus_endpoint_serves_text_format_and_honours_the_token(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.main.settings", Settings(metrics_token=SecretStr("operator-token-value"))
    )
    with TestClient(app) as client:
        denied = client.get("/api/v1/metrics/prometheus")
        allowed = client.get(
            "/api/v1/metrics/prometheus",
            headers={"Authorization": "Bearer operator-token-value"},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.headers["content-type"].startswith("text/plain")
    assert "analytics_http_requests_total" in allowed.text


def test_http_metrics_use_the_route_template_not_the_raw_path() -> None:
    with TestClient(app) as client:
        client.get("/api/v1/schema/tables/vehicles")
        client.get("/api/v1/schema/tables/not_a_table")
        client.get("/api/v1/definitely/not/a/route")
        text = client.get("/api/v1/metrics/prometheus").text

    assert 'route="/api/v1/schema/tables/{table_name}"' in text
    assert "not_a_table" not in text
    assert "/definitely/not/a/route" not in text
    assert 'route="unmatched"' in text


# -- audit ----------------------------------------------------------------------------------


def test_audit_events_have_no_field_that_could_hold_content() -> None:
    fields = set(AuditEvent.__dataclass_fields__)

    assert fields.isdisjoint({"question", "sql", "query", "prompt", "rows", "token", "password"})
    assert {"request_id", "principal", "sql_hash", "tables", "row_count", "outcome"} <= fields


def test_sql_hash_ignores_whitespace_and_does_not_reveal_the_statement() -> None:
    first = hash_sql("SELECT COUNT(*)   FROM vehicles")
    second = hash_sql("SELECT COUNT(*) FROM vehicles\n")

    assert first == second
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert "vehicles" not in first


def _sqlite_engine():
    return create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )


def _ask_client() -> TestClient:
    engine = _sqlite_engine()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE vehicles (id INTEGER, status TEXT)"))
        connection.execute(text("INSERT INTO vehicles VALUES (1, 'active')"))
    service = SQLGenerationService(
        MockLLMProvider(), analytics_service=AnalyticsQueryService(engine)
    )
    app.dependency_overrides[get_sql_generation_service] = lambda: service
    return TestClient(app)


def test_every_ask_is_audited_without_question_or_sql_text(caplog) -> None:
    caplog.set_level(logging.INFO, logger="audit")
    try:
        with _ask_client() as client:
            ok = client.post("/api/v1/analytics/ask", json={"question": QUESTION})
            failed = client.post(
                "/api/v1/analytics/ask", json={"question": "a question the mock cannot answer"}
            )
    finally:
        app.dependency_overrides.pop(get_sql_generation_service, None)

    records = [record for record in caplog.records if record.name == "audit"]
    assert ok.status_code == 200
    assert failed.status_code == 422
    assert [record.outcome for record in records] == ["success", "error"]
    success, error = records
    assert success.request_id == ok.json()["request_id"]
    assert success.sql_hash == hash_sql(ok.json()["sql"])
    assert success.tables == ["vehicles"]
    assert success.result_row_count == 1
    assert error.error_code == "MOCK_QUERY_UNSUPPORTED"
    everything = " ".join(str(vars(record)) for record in records)
    assert QUESTION not in everything
    assert "a question the mock cannot answer" not in everything
    assert "SELECT" not in everything


def test_feedback_is_recorded_in_the_audit_trail_without_free_text(caplog) -> None:
    caplog.set_level(logging.INFO, logger="audit")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/analytics/feedback",
            json={"request_id": "req-123", "helpful": False, "comment": "my private notes"},
        )
        invalid = client.post(
            "/api/v1/analytics/feedback", json={"request_id": "bad id with spaces", "helpful": True}
        )

    records = [record for record in caplog.records if record.name == "audit"]
    assert response.status_code == 200
    assert response.json() == {"status": "recorded"}
    assert invalid.status_code == 422
    assert len(records) == 1
    assert records[0].event == "feedback"
    assert records[0].outcome == "not_helpful"
    assert records[0].helpful is False
    assert "my private notes" not in str(vars(records[0]))


def test_database_sink_stores_identifiers_and_hashes_only() -> None:
    engine = _sqlite_engine()
    OperationalBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    service = AuditService([DatabaseAuditSink(factory)])

    service.record(
        AuditEvent(
            event="ask",
            outcome="success",
            request_id="req-1",
            principal="alice",
            customer_id=7,
            conversation_id="c1",
            sql_hash=hash_sql("SELECT 1"),
            tables=("vehicles", "trips"),
            row_count=12,
            duration_ms=34.5,
        )
    )

    with factory() as session:
        row = session.scalars(select(AuditRecord)).one()
    assert (row.event, row.outcome, row.principal, row.customer_id) == (
        "ask",
        "success",
        "alice",
        7,
    )
    assert row.tables == "vehicles,trips"
    assert row.row_count == 12
    assert row.sql_hash == hash_sql("SELECT 1")
    assert set(AuditRecord.__table__.columns.keys()).isdisjoint({"question", "sql", "rows"})


def test_a_failing_sink_never_fails_the_request(caplog) -> None:
    class BrokenSink:
        def write(self, event):
            raise RuntimeError("audit database is down")

    service = AuditService([BrokenSink(), LogAuditSink()])
    caplog.set_level(logging.INFO)

    service.record(AuditEvent(event="ask", outcome="success", request_id="r", principal="p"))

    assert any(record.name == "audit" for record in caplog.records)  # later sinks still run
    assert "audit sink failed" in caplog.text


def test_old_audit_records_are_purged() -> None:
    from datetime import UTC, datetime, timedelta

    engine = _sqlite_engine()
    OperationalBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session, session.begin():
        for days in (400, 10):
            session.add(
                AuditRecord(
                    occurred_at=datetime.now(UTC) - timedelta(days=days),
                    event="ask",
                    principal="alice",
                    outcome="success",
                )
            )

    removed = purge_audit_records(factory, retention_days=365)

    assert removed == 1
    with factory() as session:
        assert len(session.scalars(select(AuditRecord)).all()) == 1


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.pop(get_sql_generation_service, None)
