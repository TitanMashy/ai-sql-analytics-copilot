from functools import lru_cache

from app.analytics.dependencies import get_analytics_query_service
from app.core.config import get_settings
from app.llm.mock_provider import MockLLMProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.provider import LLMProvider, LLMProviderError
from app.services.generation import SQLGenerationService
from app.services.schema_retriever import SchemaRetriever


@lru_cache
def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if settings.llm_mode.casefold() == "mock":
        return MockLLMProvider()
    if settings.llm_mode.casefold() == "openai":
        return OpenAIProvider(settings)
    raise LLMProviderError(
        "LLM_CONFIGURATION_ERROR",
        "LLM_MODE must be either 'mock' or 'openai'.",
        503,
    )


@lru_cache
def get_sql_generation_service() -> SQLGenerationService:
    return SQLGenerationService(
        provider=get_llm_provider(),
        retriever=SchemaRetriever(),
        analytics_service=get_analytics_query_service(),
    )
