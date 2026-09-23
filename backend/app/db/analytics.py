from sqlalchemy import create_engine

from app.core.config import get_settings
from app.db.session import _engine_options

settings = get_settings()
analytics_engine = create_engine(
    settings.analytics_database_url,
    **_engine_options(settings.analytics_database_url),
)
