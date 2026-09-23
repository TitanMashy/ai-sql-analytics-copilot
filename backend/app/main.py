from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title="AI SQL Analytics Copilot API", version="0.1.0")
app.include_router(health_router, prefix="/api/v1")
