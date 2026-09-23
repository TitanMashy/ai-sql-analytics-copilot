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
    )
