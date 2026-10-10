from functools import lru_cache

from app.analytics.dependencies import get_analytics_query_service
from app.conversation.service import get_conversation_memory
from app.core.config import get_settings
from app.llm.factory import build_llm_provider
from app.llm.provider import LLMProvider
from app.services.generation import SQLGenerationService
from app.services.result_summary import ResultSummaryService
from app.services.schema_retriever import SchemaRetriever


@lru_cache
def get_llm_provider() -> LLMProvider:
    return build_llm_provider(get_settings())


@lru_cache
def get_sql_generation_service() -> SQLGenerationService:
    return SQLGenerationService(
        provider=get_llm_provider(),
        retriever=SchemaRetriever(),
        analytics_service=get_analytics_query_service(),
        max_repair_retries=get_settings().max_repair_retries,
        summary_service=ResultSummaryService(enabled=get_settings().enable_result_summary),
        conversation_memory=get_conversation_memory(),
        request_deadline_seconds=get_settings().request_deadline_seconds,
    )
