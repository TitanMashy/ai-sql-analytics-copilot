from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.analytics.service import AnalyticsQueryService, AnalyticsServiceError
from app.analytics.validator import SQLValidator
from app.db.schema_metadata import get_schema_metadata
from app.llm.mock_provider import MockLLMProvider
from app.llm.parser import parse_llm_response
from app.llm.prompt import SQLPromptBuilder
from app.llm.provider import LLMGeneration, LLMProviderError
from app.main import app
from app.services.generation import SQLGenerationService
from app.services.llm_dependencies import get_sql_generation_service
from app.services.schema_retriever import SchemaRetriever

QUESTIONS = [
    "What is the total number of active vehicles?",
    "What were the top 10 customers by revenue?",
    "Show monthly revenue for the last 12 months.",
    "Which vehicles had the highest idle time?",
    "Show fuel consumption by vehicle.",
]


def test_mock_provider_generates_five_realistic_questions() -> None:
    retriever = SchemaRetriever()
    provider = MockLLMProvider()
    validator = SQLValidator()

    for question in QUESTIONS:
        context = retriever.retrieve(question)
        generation = provider.generate_sql(question, context)
        assert validator.validate(generation.sql).valid
        assert generation.sql.startswith("SELECT")
        assert generation.tables_used


def test_schema_retriever_narrowed_mode_selects_revenue_tables() -> None:
    context = SchemaRetriever(full_schema=False).retrieve(
        "Which customers generated the most revenue?"
    )

    assert {"customers", "invoices", "payments"}.issubset(context.table_names)
    assert "vehicles" not in context.table_names
    assert any(definition.name == "revenue" for definition in context.business_definitions)


def test_schema_retriever_includes_every_table_by_default_with_relevant_first() -> None:
    context = SchemaRetriever().retrieve("Which customers generated the most revenue?")

    assert len(context.table_names) == len(get_schema_metadata())
    assert context.table_names[0] in {"invoices", "customers"}
    assert "vehicles" in context.table_names


def test_follow_up_without_keywords_still_sees_the_whole_schema() -> None:
    context = SchemaRetriever().retrieve("and break that down by month?")

    assert len(context.table_names) == len(get_schema_metadata())


def test_narrowed_follow_up_uses_the_conversation_instead_of_an_arbitrary_fallback() -> None:
    retriever = SchemaRetriever(full_schema=False)

    with_context = retriever.retrieve(
        "and break that down by month?",
        "user: Show revenue by customer\nassistant: Acme led revenue.\n  Tables: invoices",
    )
    without_context = retriever.retrieve("and break that down by month?")

    assert "invoices" in with_context.table_names
    assert any(definition.name == "revenue" for definition in with_context.business_definitions)
    assert len(without_context.table_names) == len(get_schema_metadata())


def test_prompt_contains_schema_and_business_definitions() -> None:
    question = "What were the top customers by revenue?"
    context = SchemaRetriever().retrieve(question)
    prompt = SQLPromptBuilder().build(question, context)

    assert "PostgreSQL" in prompt
    assert "invoices.total_amount" in prompt
    assert "customers" in prompt
    assert "Do not invent identifiers" in prompt
    assert "OPENAI_API_KEY" not in prompt


FIXED_NOW = datetime(2026, 3, 14, 9, 30, tzinfo=UTC)


def test_prompt_includes_current_date_enum_values_and_untrusted_data_markers() -> None:
    builder = SQLPromptBuilder(clock=lambda: FIXED_NOW)
    context = SchemaRetriever().retrieve("How many active vehicles are there?")

    prompt = builder.build_user_prompt("How many active vehicles are there?", context)

    assert "Current date and time: 2026-03-14 09:30 UTC" in prompt
    assert "status (VARCHAR(20)) one of 'active', 'inactive', 'maintenance', 'retired'" in prompt
    assert 'User question (JSON-encoded untrusted data): "How many active vehicles' in prompt
    assert "Relevant schema:" in prompt
    assert "Business definitions:" in prompt


def test_prompt_never_shows_personal_data_columns() -> None:
    context = SchemaRetriever().retrieve("List users and drivers")

    prompt = SQLPromptBuilder().build_user_prompt("List users and drivers", context)

    for hidden in ("email", "license_number", "phone"):
        assert hidden not in prompt


def test_rules_live_in_the_system_instruction_not_the_user_prompt() -> None:
    builder = SQLPromptBuilder(clock=lambda: FIXED_NOW)
    context = SchemaRetriever().retrieve("Show revenue")

    system = builder.system_instruction()
    user = builder.build_user_prompt("Show revenue", context)

    assert "Do not invent identifiers" in system
    assert "only standard aggregate" in system
    assert "Do not invent identifiers" not in user


def test_repair_prompt_is_built_once_and_carries_hint_sql_and_context() -> None:
    builder = SQLPromptBuilder(clock=lambda: FIXED_NOW)
    context = SchemaRetriever().retrieve("Show revenue")

    prompt = builder.build_repair_prompt(
        "Show revenue",
        context,
        "SELECT missing FROM invoices",
        "SQLSTATE 42703: column \"missing\" does not exist",
        conversation_context="user: earlier",
    )

    assert "SELECT missing FROM invoices" in prompt
    assert "42703" in prompt
    assert "user: earlier" in prompt
    assert "Repair the SQL" in prompt


def test_parser_accepts_code_fence_and_ignores_extra_fields() -> None:
    response = parse_llm_response(
        """```json
        {"sql":"SELECT 1", "explanation":"test", "tables_used":[], "unexpected":"ignored"}
        ```"""
    )

    assert response.sql == "SELECT 1"
    assert response.explanation == "test"


@pytest.mark.parametrize(
    "content",
    ["not json", "{}", '{"sql":""}', "[]"],
)
def test_parser_rejects_malformed_or_empty_responses(content: str) -> None:
    with pytest.raises(LLMProviderError) as error:
        parse_llm_response(content)

    assert error.value.code == "INVALID_LLM_RESPONSE"


@pytest.fixture
def generation_client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE vehicles (id INTEGER, status TEXT)"))
        connection.execute(text("INSERT INTO vehicles VALUES (1, 'active'), (2, 'inactive')"))
        connection.execute(
            text(
                "CREATE TABLE invoices (id INTEGER, total_amount NUMERIC, status TEXT, "
                "customer_id INTEGER, invoice_date DATE)"
            )
        )
        connection.execute(text("CREATE TABLE customers (id INTEGER, company_name TEXT)"))
        connection.execute(
            text("CREATE TABLE trips (id INTEGER, vehicle_id INTEGER, idle_time_minutes INTEGER)")
        )
        connection.execute(
            text(
                "CREATE TABLE fuel_records (id INTEGER, vehicle_id INTEGER, liters NUMERIC, "
                "total_cost NUMERIC)"
            )
        )

    query_service = AnalyticsQueryService(engine)
    generation_service = SQLGenerationService(
        provider=MockLLMProvider(),
        analytics_service=query_service,
    )
    app.dependency_overrides[get_sql_generation_service] = lambda: generation_service
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_generate_endpoint_does_not_execute(generation_client: TestClient) -> None:
    response = generation_client.post(
        "/api/v1/analytics/generate",
        json={"question": "What is the total number of active vehicles?"},
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "mock"
    assert response.json()["sql"].startswith("SELECT")
    assert response.json()["tables_used"] == ["vehicles"]


def test_ask_endpoint_validates_and_executes_generated_sql(
    generation_client: TestClient,
) -> None:
    response = generation_client.post(
        "/api/v1/analytics/ask",
        json={"question": "What is the total number of active vehicles?"},
    )

    assert response.status_code == 200
    assert response.json()["rows"] == [{"active_vehicle_count": 1}]
    assert response.json()["row_count"] == 1


def test_generated_write_sql_is_rejected_before_execution() -> None:
    class BadProvider:
        name = "bad-test-provider"

        def generate_sql(
            self, question, schema_context, conversation_context=None
        ) -> LLMGeneration:
            return LLMGeneration(
                sql="DELETE FROM vehicles",
                explanation="bad",
                tables_used=["vehicles"],
            )

    engine = create_engine("sqlite://", poolclass=StaticPool)
    service = SQLGenerationService(
        provider=BadProvider(),
        analytics_service=AnalyticsQueryService(engine),
    )

    with pytest.raises(AnalyticsServiceError) as error:
        service.ask("delete vehicles")

    assert error.value.code == "QUERY_SECURITY_ERROR"
