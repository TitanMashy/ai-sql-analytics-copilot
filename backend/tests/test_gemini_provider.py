from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.analytics.service import AnalyticsQueryService
from app.core.config import Settings
from app.llm.gemini_provider import GeminiProvider
from app.llm.provider import LLMProviderError
from app.services.generation import SQLGenerationService
from app.services.schema_retriever import SchemaRetriever


class FakeModels:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.responses.pop(0))


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.models = FakeModels(responses)


def _settings() -> Settings:
    return Settings(gemini_api_key="test-key", gemini_model="gemini-test")


def test_gemini_provider_uses_structured_json_and_shared_parser() -> None:
    client = FakeClient(
        [
            '{"sql":"SELECT COUNT(*) AS active_count FROM vehicles WHERE status = \'active\'",'
            '"explanation":"Counts active vehicles.","tables_used":["vehicles"],"confidence":0.91}'
        ]
    )
    provider = GeminiProvider(_settings(), client=client)
    context = SchemaRetriever().retrieve("What is the active vehicle count?")

    result = provider.generate_sql("What is the active vehicle count?", context)

    call = client.models.calls[0]
    config = call["config"]
    assert result.sql.startswith("SELECT COUNT")
    assert result.tables_used == ["vehicles"]
    assert call["model"] == "gemini-test"
    assert config.response_mime_type == "application/json"
    assert config.response_schema is not None


def test_gemini_provider_repair_uses_same_structured_path() -> None:
    client = FakeClient(
        [
            '{"sql":"SELECT id FROM vehicles","explanation":"Repaired query",'
            '"tables_used":["vehicles"]}'
        ]
    )
    provider = GeminiProvider(_settings(), client=client)
    context = SchemaRetriever().retrieve("show vehicle ids")

    result = provider.repair_sql(
        "show vehicle ids",
        "SELECT missing FROM vehicles",
        "Unknown column",
        context,
    )

    assert result.sql == "SELECT id FROM vehicles"
    assert "Unknown column" in str(client.models.calls[0]["contents"])


def test_gemini_provider_handles_empty_response() -> None:
    provider = GeminiProvider(_settings(), client=FakeClient([""]))
    context = SchemaRetriever().retrieve("show vehicle ids")

    with pytest.raises(LLMProviderError) as error:
        provider.generate_sql("show vehicle ids", context)

    assert error.value.code == "INVALID_LLM_RESPONSE"


def test_gemini_generated_sql_uses_existing_validation_before_execution() -> None:
    client = FakeClient(
        [
            '{"sql":"SELECT COUNT(*) AS active_count FROM vehicles WHERE status = \'active\'",'
            '"explanation":"Counts active vehicles.","tables_used":["vehicles"]}'
        ]
    )
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE vehicles (id INTEGER, status TEXT)"))
        connection.execute(text("INSERT INTO vehicles VALUES (1, 'active'), (2, 'inactive')"))

    service = SQLGenerationService(
        provider=GeminiProvider(_settings(), client=client),
        analytics_service=AnalyticsQueryService(engine),
    )

    result = service.ask("What is the active vehicle count?")

    assert result.result.rows == [{"active_count": 1}]


def test_missing_gemini_key_is_configuration_error() -> None:
    with pytest.raises(LLMProviderError) as error:
        GeminiProvider(Settings(gemini_api_key=None))

    assert error.value.code == "LLM_CONFIGURATION_ERROR"
