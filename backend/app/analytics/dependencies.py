from functools import lru_cache

from app.analytics.service import AnalyticsQueryService
from app.core.config import get_settings
from app.db.analytics import analytics_engine


@lru_cache
def get_analytics_query_service() -> AnalyticsQueryService:
    settings = get_settings()
    return AnalyticsQueryService(
        engine=analytics_engine,
        max_result_rows=settings.max_result_rows,
        query_timeout_seconds=settings.query_timeout_seconds,
        max_query_joins=settings.max_query_joins,
        max_query_nesting=settings.max_query_nesting,
    )
