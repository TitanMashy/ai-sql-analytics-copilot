from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(default="sqlite:///./app.db", validation_alias="DATABASE_URL")
    analytics_database_url: str = Field(
        default="sqlite:///./analytics.db",
        validation_alias="ANALYTICS_DATABASE_URL",
    )
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_MODEL")
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-flash-latest", validation_alias="GEMINI_MODEL")
    llm_mode: str = Field(default="mock", validation_alias="LLM_MODE")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    max_result_rows: int = Field(default=1000, validation_alias="MAX_RESULT_ROWS")
    query_timeout_seconds: float = Field(default=10.0, validation_alias="QUERY_TIMEOUT_SECONDS")
    max_query_joins: int = Field(default=5, validation_alias="MAX_QUERY_JOINS")
    max_query_nesting: int = Field(default=3, validation_alias="MAX_QUERY_NESTING")
    max_repair_retries: int = Field(default=3, validation_alias="MAX_REPAIR_RETRIES")
    enable_result_summary: bool = Field(default=True, validation_alias="ENABLE_RESULT_SUMMARY")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
