"""Regression evidence for the security invariants that cut across providers.

The model is untrusted. Whatever provider is configured, its SQL must pass validation before the
database is touched, secrets must not reach responses or logs, and the model layer and the SQL
safety layer must stay independent of each other. Each test names the property it protects.
"""

import ast
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.analytics.service import AnalyticsQueryService, AnalyticsServiceError
from app.core.auth import Principal
from app.llm.langchain_provider import LangChainSQLProvider
from app.llm.provider import LLMGeneration
from app.main import app
from app.services.generation import SQLGenerationService
from app.services.llm_dependencies import get_sql_generation_service

APP = Path(__file__).resolve().parents[1] / "app"
MODEL_SIDE = ("app/llm", "app/core/llm_tracing.py")
SQL_SIDE = ("app/analytics", "app/db")
FORBIDDEN_FOR_MODEL_SIDE = ("sqlalchemy", "app.analytics", "app.db", "psycopg")
FORBIDDEN_FOR_SQL_SIDE = ("langchain", "langchain_core", "langsmith", "app.llm", "ollama")


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _python_files(*roots: str):
    base = APP.parent
    for root in roots:
        target = base / root
        yield from [target] if target.is_file() else sorted(target.rglob("*.py"))


def _violations(roots, forbidden) -> list[str]:
    found = []
    for path in _python_files(*roots):
        for module in _imports(path):
            if any(module == name or module.startswith(name + ".") for name in forbidden):
                found.append(f"{path.relative_to(APP.parent)} imports {module}")
    return found


# -- the model layer and the SQL safety layer do not depend on each other --


def test_the_model_layer_cannot_reach_the_database() -> None:
    # A model wrapper that imported SQLAlchemy or the executor could execute SQL itself.
    allowed = {"app/llm/factory.py"}  # builds providers only; it must still not touch the database
    found = [
        v for v in _violations(MODEL_SIDE, FORBIDDEN_FOR_MODEL_SIDE) if v.split()[0] not in allowed
    ]

    assert found == []


def test_the_sql_safety_layer_does_not_depend_on_langchain_or_the_model_layer() -> None:
    # Validation and read-only execution must stay correct whatever drives the model.
    assert _violations(SQL_SIDE, FORBIDDEN_FOR_SQL_SIDE) == []


# -- no provider path reaches the database before validation ---------------------------------------


class StubProvider:
    """A provider that is not LangChain at all: the boundary is the protocol, not a class."""

    name = "stub"

    def __init__(self, *sql: str) -> None:
        self.sql = list(sql)

    def generate_sql(self, question, schema_context, conversation_context=None):
        return LLMGeneration(sql=self.sql.pop(0), explanation="x", tables_used=[])

    def repair_sql(
        self, question, original_sql, error_message, schema_context, conversation_context=None
    ):
        return LLMGeneration(sql=self.sql.pop(0), explanation="x", tables_used=[])


class ScriptedChat:
    def __init__(self, *sql: str) -> None:
        self.sql = list(sql)

    def invoke(self, messages, *args, **kwargs):
        return SimpleNamespace(
            content=json.dumps({"sql": self.sql.pop(0), "explanation": "x", "tables_used": []})
        )


def _providers(*sql: str):
    return {
        "protocol-stub": StubProvider(*sql),
        "langchain": LangChainSQLProvider(
            name="gemini", label="Gemini", model="m", chat_model=ScriptedChat(*sql), max_retries=0
        ),
    }


FORBIDDEN_SQL = [
    "DROP TABLE vehicles",
    "DELETE FROM vehicles",
    "INSERT INTO vehicles VALUES (9, 'x')",
    "SELECT * FROM pg_shadow",
    "SELECT email FROM users",  # personal data
    "SELECT 1; DROP TABLE vehicles",
    "SELECT pg_sleep(30)",
    "SELECT current_setting('app.scope')",
    "SELECT * FROM secret_table",
]


def _guarded_service(provider, **options):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE vehicles (id INTEGER, status TEXT)"))
    opened = []

    def connect_is_forbidden(*args, **kwargs):
        opened.append(True)
        raise AssertionError("the database was opened for SQL that did not pass validation")

    engine.connect = connect_is_forbidden  # type: ignore[method-assign]
    service = SQLGenerationService(
        provider, analytics_service=AnalyticsQueryService(engine), **options
    )
    return service, opened


@pytest.mark.parametrize("provider_name", ["protocol-stub", "langchain"])
@pytest.mark.parametrize("sql", FORBIDDEN_SQL)
def test_forbidden_sql_never_opens_a_database_connection(provider_name, sql) -> None:
    provider = _providers(*([sql] * 5))[provider_name]
    service, opened = _guarded_service(provider, max_repair_retries=2)

    with pytest.raises(AnalyticsServiceError):
        service.ask("show vehicles")

    assert opened == []


@pytest.mark.parametrize("provider_name", ["protocol-stub", "langchain"])
def test_a_repaired_statement_is_validated_before_it_can_run(provider_name) -> None:
    # The first answer is repairable (unknown column); the "repair" is a destructive statement.
    provider = _providers(
        "SELECT missing_column FROM vehicles", "DROP TABLE vehicles", "DROP TABLE vehicles"
    )[provider_name]
    service, opened = _guarded_service(provider, max_repair_retries=2)

    with pytest.raises(AnalyticsServiceError):
        service.ask("show vehicles")

    assert opened == []


@pytest.mark.parametrize("provider_name", ["protocol-stub", "langchain"])
def test_the_provider_cannot_change_who_the_query_runs_as(provider_name) -> None:
    seen = []
    provider = _providers("SELECT COUNT(*) AS n FROM vehicles")[provider_name]
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE vehicles (id INTEGER)"))
    analytics = AnalyticsQueryService(engine)
    original = analytics.execute

    def spy(sql, **kwargs):
        seen.append(kwargs.get("principal"))
        return original(sql, **kwargs)

    analytics.execute = spy  # type: ignore[method-assign]
    caller = Principal("tenant-user", customer_id=7, roles=("analyst",))

    SQLGenerationService(provider, analytics_service=analytics).ask("count", principal=caller)

    # The tenant identity comes from the request's principal, never from the model path.
    assert seen == [caller]


# -- secrets and provider text do not reach responses or logs --


SECRET = "AIzaSy-test-secret-key-value-1234567890"


def test_a_provider_failure_does_not_leak_its_message_key_or_request_into_the_response_or_logs(
    caplog,
) -> None:
    leaky = httpx.ConnectError(f"connect failed for key={SECRET} prompt=SELECT secret FROM vault")
    provider = LangChainSQLProvider(
        name="gemini",
        label="Gemini",
        model="m",
        chat_model=SimpleNamespace(invoke=lambda *a, **k: (_ for _ in ()).throw(leaky)),
        max_retries=1,
        sleep=lambda seconds: None,
    )
    service = SQLGenerationService(
        provider, analytics_service=AnalyticsQueryService(create_engine("sqlite://"))
    )
    app.dependency_overrides[get_sql_generation_service] = lambda: service
    try:
        with caplog.at_level(logging.DEBUG):
            with TestClient(app) as client:
                response = client.post("/api/v1/analytics/ask", json={"question": "count vehicles"})
    finally:
        app.dependency_overrides.pop(get_sql_generation_service, None)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_PROVIDER_UNAVAILABLE"
    logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for text_ in (response.text, logged):
        assert SECRET not in text_
        assert "SELECT secret" not in text_
        assert "connect failed" not in text_


def _ask_with_failing_database(monkeypatch, environment: str):
    from app.core.config import Settings

    monkeypatch.setattr("app.main.settings", Settings.model_construct(environment=environment))
    provider = StubProvider("SELECT COUNT(*) AS n FROM vehicles")
    engine = create_engine(
        "sqlite://", poolclass=StaticPool
    )  # no vehicles table: the driver errors
    service = SQLGenerationService(
        provider, analytics_service=AnalyticsQueryService(engine), max_repair_retries=0
    )
    app.dependency_overrides[get_sql_generation_service] = lambda: service
    try:
        with TestClient(app) as client:
            return client.post("/api/v1/analytics/ask", json={"question": "count vehicles"})
    finally:
        app.dependency_overrides.pop(get_sql_generation_service, None)


def test_production_error_responses_do_not_echo_the_sql_or_the_driver_message(monkeypatch) -> None:
    response = _ask_with_failing_database(monkeypatch, "production")

    body = response.text.lower()
    assert response.status_code >= 400
    assert "debug" not in response.json()["error"]
    assert "no such table" not in body and "select count" not in body and "sqlite" not in body


def test_outside_production_only_the_generation_failure_carries_a_debug_block(monkeypatch) -> None:
    # Documented development behaviour (README and security.md): the dashboard shows the failed SQL.
    # It is the single place a database message can reach a response, and production never has it.
    response = _ask_with_failing_database(monkeypatch, "development")

    error = response.json()["error"]
    assert error["code"] == "QUERY_GENERATION_FAILED"
    assert set(error["debug"]) == {"sql", "last_error"}
