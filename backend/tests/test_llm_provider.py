"""The model boundary: factory selection, the LangChain-backed provider, errors, retries.

No test here calls an external service. A fake chat model stands in for LangChain's, and the
real chat classes are only constructed (which makes no network call).
"""

import json
import logging
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.analytics.service import AnalyticsQueryService, AnalyticsServiceError
from app.core.config import DEFAULT_GEMINI_MODEL, Settings
from app.llm.errors import classify_provider_error
from app.llm.factory import build_chat_model, build_llm_provider
from app.llm.langchain_provider import LangChainSQLProvider
from app.llm.mock_provider import MockLLMProvider
from app.llm.provider import LLMProviderError
from app.services.generation import SQLGenerationService
from app.services.schema_retriever import SchemaRetriever

GOOD = (
    '{"sql":"SELECT COUNT(*) AS active_count FROM vehicles WHERE status = \'active\'",'
    '"explanation":"Counts active vehicles.","tables_used":["vehicles"],"confidence":0.91}'
)


class FakeChatModel:
    """Returns scripted replies; a scripted exception is raised instead of returned."""

    def __init__(self, *replies) -> None:
        self.replies = list(replies)
        self.calls: list[list] = []

    def invoke(self, messages, *args, **kwargs):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return SimpleNamespace(content=reply)


def _provider(chat_model, **overrides) -> LangChainSQLProvider:
    options = {
        "name": "gemini",
        "label": "Gemini",
        "model": "gemini-test",
        "chat_model": chat_model,
        "max_retries": 1,
        "retry_window_seconds": 60.0,
        "sleep": lambda seconds: None,
    }
    options.update(overrides)
    return LangChainSQLProvider(**options)


def _context(question: str = "show vehicle ids"):
    return SchemaRetriever().retrieve(question)


# -- generation and repair ----------------------------------------------------------------------


def test_generation_sends_rules_as_the_system_message_and_data_as_the_user_message() -> None:
    chat = FakeChatModel(GOOD)
    provider = _provider(chat)

    result = provider.generate_sql("How many active vehicles?", _context(), "user: earlier")

    system, human = chat.calls[0]
    assert result.sql.startswith("SELECT COUNT")
    assert result.tables_used == ["vehicles"]
    assert "Do not invent identifiers" in system.content
    # The rules are not repeated in the user prompt, which carries only data.
    assert "Do not invent identifiers" not in human.content
    assert "user: earlier" in human.content


def test_repair_goes_through_the_same_path_with_the_error_hint() -> None:
    chat = FakeChatModel(
        '{"sql":"SELECT id FROM vehicles","explanation":"Repaired","tables_used":[]}'
    )
    provider = _provider(chat)

    result = provider.repair_sql(
        "show vehicle ids", "SELECT missing FROM vehicles", "Unknown column", _context(), "user: q"
    )

    prompt = chat.calls[0][1].content
    assert result.sql == "SELECT id FROM vehicles"
    assert "Unknown column" in prompt and "SELECT missing FROM vehicles" in prompt


def test_response_content_may_be_a_list_of_blocks() -> None:
    blocks = [
        {"type": "text", "text": '{"sql":"SELECT 1","explanation":"x",'},
        {"type": "text", "text": '"tables_used":[]}'},
    ]

    result = _provider(FakeChatModel(blocks)).generate_sql("q", _context())

    assert result.sql == "SELECT 1"


@pytest.mark.parametrize(
    "reply", ["", "   ", [], "not json at all", '{"explanation":"no sql"}', '{"sql":""}']
)
def test_empty_or_malformed_output_is_a_classified_failure_not_guessed_sql(reply) -> None:
    provider = _provider(FakeChatModel(reply))

    with pytest.raises(LLMProviderError) as error:
        provider.generate_sql("q", _context())

    assert error.value.code == "INVALID_LLM_RESPONSE"
    assert error.value.status_code == 502


def test_a_json_code_fence_is_accepted_by_the_shared_parser() -> None:
    fenced = '```json\n{"sql":"SELECT 1","explanation":"x","tables_used":[]}\n```'

    assert _provider(FakeChatModel(fenced)).generate_sql("q", _context()).sql == "SELECT 1"


# -- nothing a provider returns reaches the database unvalidated -----------------------------------


def _vehicle_engine():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE vehicles (id INTEGER, status TEXT)"))
        connection.execute(text("INSERT INTO vehicles VALUES (1, 'active'), (2, 'inactive')"))
    return engine


def test_valid_generated_sql_is_validated_then_executed() -> None:
    service = SQLGenerationService(
        provider=_provider(FakeChatModel(GOOD)),
        analytics_service=AnalyticsQueryService(_vehicle_engine()),
    )

    assert service.ask("What is the active vehicle count?").result.rows == [{"active_count": 1}]


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE vehicles",
        "DELETE FROM vehicles",
        "SELECT * FROM users",
        "SELECT pg_sleep(10)",
        "SELECT 1; DROP TABLE vehicles",
    ],
)
def test_dangerous_sql_from_any_provider_never_executes(sql: str) -> None:
    engine = _vehicle_engine()
    bad = json.dumps({"sql": sql, "explanation": "x", "tables_used": []})
    # The same bad answer comes back for the initial attempt and for every repair.
    service = SQLGenerationService(
        provider=_provider(FakeChatModel(*([bad] * 6))),
        analytics_service=AnalyticsQueryService(engine),
        max_repair_retries=2,
    )

    with pytest.raises(AnalyticsServiceError):
        service.ask("show vehicles")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM vehicles")).scalar() == 2


def test_repair_is_bounded_and_every_repaired_statement_is_revalidated() -> None:
    # An unknown column is a repairable validation failure, so the loop runs, and every repaired
    # statement is validated again; the answer never gets better, so it must stop.
    bad = json.dumps(
        {"sql": "SELECT missing_column FROM vehicles", "explanation": "x", "tables_used": []}
    )
    chat = FakeChatModel(*([bad] * 10))
    service = SQLGenerationService(
        provider=_provider(chat),
        analytics_service=AnalyticsQueryService(_vehicle_engine()),
        max_repair_retries=2,
    )

    with pytest.raises(AnalyticsServiceError):
        service.ask("show vehicles")

    # One initial generation plus at most two repairs; never an unbounded loop.
    assert len(chat.calls) == 3


def test_security_rejections_are_never_sent_back_for_repair() -> None:
    bad = json.dumps({"sql": "DROP TABLE vehicles", "explanation": "x", "tables_used": []})
    chat = FakeChatModel(*([bad] * 10))
    service = SQLGenerationService(
        provider=_provider(chat),
        analytics_service=AnalyticsQueryService(_vehicle_engine()),
        max_repair_retries=2,
    )

    with pytest.raises(AnalyticsServiceError):
        service.ask("show vehicles")

    assert len(chat.calls) == 1


# -- error classification --------------------------------------------------------------------------


class _Coded(Exception):
    def __init__(self, code: int, message: str = "") -> None:
        super().__init__(message)
        self.code = code


def _wrapped(code: int, message: str) -> Exception:
    """Shaped like LangChain's wrapper: the HTTP code is on the wrapped ``__cause__``."""
    try:
        try:
            raise _Coded(code, message)
        except _Coded as cause:
            raise RuntimeError("Error calling model") from cause
    except RuntimeError as error:
        return error


@pytest.mark.parametrize(
    ("error", "code", "status", "retryable"),
    [
        (_wrapped(429, "RESOURCE_EXHAUSTED"), "LLM_RATE_LIMITED", 503, False),
        (_wrapped(404, "model not found"), "LLM_MODEL_UNAVAILABLE", 503, False),
        (_wrapped(503, "overloaded"), "LLM_PROVIDER_UNAVAILABLE", 503, True),
        (_wrapped(500, "internal"), "LLM_PROVIDER_UNAVAILABLE", 503, True),
        (_wrapped(504, "gateway timeout"), "LLM_TIMEOUT", 504, False),
        (_wrapped(401, "unauthorized"), "LLM_CREDENTIALS_INVALID", 503, False),
        (_wrapped(403, "forbidden"), "LLM_CREDENTIALS_INVALID", 503, False),
        # Google reports a bad key as HTTP 400, so the text has to be read as well.
        (
            _wrapped(400, "400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key."),
            "LLM_CREDENTIALS_INVALID",
            503,
            False,
        ),
        (_wrapped(400, "some other bad request"), "LLM_PROVIDER_ERROR", 502, False),
        (TimeoutError("slow"), "LLM_TIMEOUT", 504, False),
        (httpx.ReadTimeout("slow"), "LLM_TIMEOUT", 504, False),
        (httpx.ConnectError("refused"), "LLM_PROVIDER_UNAVAILABLE", 503, True),
        (ConnectionError("down"), "LLM_PROVIDER_UNAVAILABLE", 503, True),
        (ValueError("anything else"), "LLM_PROVIDER_ERROR", 502, False),
    ],
)
def test_provider_failures_map_to_stable_categories(error, code, status, retryable) -> None:
    classified = classify_provider_error(error, "Gemini")

    assert (classified.code, classified.status_code, classified.retryable) == (
        code,
        status,
        retryable,
    )


def test_classified_messages_never_echo_the_provider_text() -> None:
    secret = "sk-very-secret-key-value"
    classified = classify_provider_error(_wrapped(401, f"bad key {secret}"), "Gemini")

    assert secret not in classified.message


# -- retries ---------------------------------------------------------------------------------------


def test_a_transient_failure_is_retried_once_then_succeeds() -> None:
    chat = FakeChatModel(httpx.ConnectError("refused"), GOOD)

    assert _provider(chat).generate_sql("q", _context()).sql.startswith("SELECT COUNT")
    assert len(chat.calls) == 2


def test_retry_exhaustion_is_reported_and_bounded() -> None:
    chat = FakeChatModel(*([httpx.ConnectError("refused")] * 5))

    with pytest.raises(LLMProviderError) as error:
        _provider(chat, max_retries=2).generate_sql("q", _context())

    assert error.value.code == "LLM_PROVIDER_UNAVAILABLE"
    assert "did not recover after 3 attempts" in error.value.message
    assert len(chat.calls) == 3


@pytest.mark.parametrize(
    "failure",
    [
        _wrapped(429, "quota"),
        TimeoutError("slow"),
        _wrapped(401, "no"),
        _wrapped(404, "gone"),
        ValueError("x"),
    ],
)
def test_only_transient_infrastructure_failures_are_retried(failure) -> None:
    chat = FakeChatModel(failure, GOOD)

    with pytest.raises(LLMProviderError):
        _provider(chat).generate_sql("q", _context())

    assert len(chat.calls) == 1


def test_retries_stop_once_the_retry_window_has_passed() -> None:
    now = {"t": 0.0}
    chat = FakeChatModel(*([httpx.ConnectError("refused")] * 5))

    def sleeper(seconds: float) -> None:
        now["t"] += 100.0  # the wait itself uses up the window

    provider = _provider(
        chat, max_retries=3, retry_window_seconds=10.0, sleep=sleeper, clock=lambda: now["t"]
    )

    with pytest.raises(LLMProviderError):
        provider.generate_sql("q", _context())

    assert len(chat.calls) == 2


def test_provider_failure_logs_carry_metadata_only(caplog) -> None:
    secret_question = "salary of Alice at Acme"
    chat = FakeChatModel(httpx.ConnectError("refused"), httpx.ConnectError("refused"))

    with caplog.at_level(logging.WARNING, logger="app.llm.langchain_provider"):
        with pytest.raises(LLMProviderError):
            _provider(chat).generate_sql(secret_question, _context())

    text_logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert caplog.records
    assert secret_question not in text_logged
    assert "SELECT" not in text_logged
    assert caplog.records[0].llm_provider == "gemini"
    assert caplog.records[0].error_code == "LLM_PROVIDER_UNAVAILABLE"


# -- the factory ---------------------------------------------------------------------------------


def test_mock_is_the_default_and_needs_nothing() -> None:
    provider = build_llm_provider(Settings())

    assert isinstance(provider, MockLLMProvider)
    assert provider.name == "mock"


def test_mock_is_deterministic_and_offline() -> None:
    question = "What is the total number of active vehicles?"
    first = build_llm_provider(Settings()).generate_sql(question, _context(question))
    second = build_llm_provider(Settings()).generate_sql(question, _context(question))

    assert first == second


def test_gemini_is_built_through_langchain_with_one_retry_policy() -> None:
    settings = Settings(llm_provider="gemini", gemini_api_key="test-key", llm_timeout_seconds=7.5)

    provider = build_llm_provider(settings)
    chat = provider.chat_model

    assert isinstance(provider, LangChainSQLProvider)
    assert (provider.name, provider.model) == ("gemini", DEFAULT_GEMINI_MODEL)
    # LangChain's own default is 6 retries; the application applies the only retry.
    assert chat.max_retries == 0
    assert chat.timeout == 7.5
    assert chat.temperature == 0.0
    assert chat.response_mime_type == "application/json"


def test_gemini_model_is_configurable_through_llm_model() -> None:
    settings = Settings(llm_provider="gemini", gemini_api_key="k", llm_model="gemini-custom")

    assert build_llm_provider(settings).model == "gemini-custom"


def test_gemini_without_a_key_is_a_clear_configuration_error() -> None:
    with pytest.raises(LLMProviderError) as error:
        build_llm_provider(Settings(llm_provider="gemini", gemini_api_key=None))

    assert error.value.code == "LLM_CONFIGURATION_ERROR"
    assert "GEMINI_API_KEY" in error.value.message


def test_ollama_is_built_through_langchain_without_cloud_credentials() -> None:
    settings = Settings(
        llm_provider="ollama",
        llm_model="llama3.1:8b",
        ollama_base_url="http://host.docker.internal:11434/",
        llm_timeout_seconds=12,
    )

    provider = build_llm_provider(settings)
    chat = provider.chat_model

    assert (provider.name, provider.model) == ("ollama", "llama3.1:8b")
    assert chat.base_url == "http://host.docker.internal:11434"
    assert chat.format == "json"
    assert chat.temperature == 0.0
    assert chat.validate_model_on_init is False  # never pulls or probes a model implicitly
    assert chat.client_kwargs == {"timeout": 12}


def test_ollama_requires_an_explicit_model() -> None:
    with pytest.raises(ValueError, match="LLM_MODEL is required"):
        Settings(llm_provider="ollama")


def test_an_unknown_provider_fails_validation_and_never_falls_back() -> None:
    with pytest.raises(ValueError):
        Settings(llm_provider="openai")


def test_chat_models_are_not_built_for_the_mock() -> None:
    with pytest.raises(LLMProviderError) as error:
        build_chat_model(Settings())

    assert error.value.code == "LLM_CONFIGURATION_ERROR"


def test_mock_is_refused_in_production() -> None:
    settings = Settings.model_construct(llm_provider="mock", environment="production")

    with pytest.raises(LLMProviderError) as error:
        build_llm_provider(settings)

    assert error.value.code == "LLM_CONFIGURATION_ERROR"


def test_the_retry_window_stays_inside_the_request_deadline() -> None:
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="k",
        llm_timeout_seconds=30,
        request_deadline_seconds=10,
    )

    assert build_llm_provider(settings).retry_window_seconds == 5.0


# -- settings --------------------------------------------------------------------------------------


def test_the_removed_setting_names_refuse_to_start_instead_of_being_ignored(monkeypatch) -> None:
    from app.core.config import ConfigurationError, get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LLM_MODE", "gemini")
    try:
        with pytest.raises(ConfigurationError) as error:
            get_settings()
    finally:
        get_settings.cache_clear()

    assert "LLM_MODE" in str(error.value) and "LLM_PROVIDER" in str(error.value)

    get_settings.cache_clear()
    monkeypatch.delenv("LLM_MODE")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-x")
    try:
        with pytest.raises(ConfigurationError) as error:
            get_settings()
    finally:
        get_settings.cache_clear()

    assert "GEMINI_MODEL" in str(error.value) and "LLM_MODEL" in str(error.value)


def test_ollama_base_url_must_be_http() -> None:
    with pytest.raises(ValueError, match="OLLAMA_BASE_URL"):
        Settings(llm_provider="ollama", llm_model="m", ollama_base_url="ftp://host")


def test_retries_are_capped() -> None:
    with pytest.raises(ValueError):
        Settings(llm_max_retries=10)


def test_blank_removed_settings_are_treated_as_unset() -> None:
    # Compose forwards the removed names as empty strings when they are not set.
    settings = Settings(legacy_llm_mode="", legacy_gemini_model="  ")

    assert settings.llm_provider == "mock"


def test_both_removed_names_are_reported_together() -> None:
    with pytest.raises(ValueError) as error:
        Settings(legacy_llm_mode="gemini", legacy_gemini_model="gemini-x")

    message = str(error.value)
    assert "LLM_MODE" in message and "GEMINI_MODEL" in message
    assert "gemini-x" not in message  # the value is never printed
