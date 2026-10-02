from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(
        default="sqlite:///./app.db", validation_alias="DATABASE_URL", repr=False
    )
    analytics_database_url: str = Field(
        default="sqlite:///./analytics.db",
        validation_alias="ANALYTICS_DATABASE_URL",
        repr=False,
    )
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias="OPENAI_API_KEY", repr=False
    )
    openai_model: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_MODEL")
    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias="GEMINI_API_KEY", repr=False
    )
    gemini_model: str = Field(default="gemini-flash-latest", validation_alias="GEMINI_MODEL")
    llm_mode: Literal["mock", "gemini", "openai"] = Field(
        default="mock", validation_alias="LLM_MODE"
    )
    environment: Literal["development", "test", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
    debug: bool = Field(default=False, validation_alias="DEBUG")
    cors_allowed_origins: list[str] = Field(
        default_factory=list, validation_alias="CORS_ALLOWED_ORIGINS"
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    max_result_rows: int = Field(default=1000, gt=0, validation_alias="MAX_RESULT_ROWS")
    query_timeout_seconds: float = Field(
        default=10.0, gt=0, validation_alias="QUERY_TIMEOUT_SECONDS"
    )
    database_pool_size: int = Field(default=5, gt=0, validation_alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=10, ge=0, validation_alias="DATABASE_MAX_OVERFLOW")
    database_pool_timeout_seconds: float = Field(
        default=5.0, gt=0, validation_alias="DATABASE_POOL_TIMEOUT_SECONDS"
    )
    database_pool_recycle_seconds: int = Field(
        default=1800, gt=0, validation_alias="DATABASE_POOL_RECYCLE_SECONDS"
    )
    database_connect_timeout_seconds: int = Field(
        default=5, gt=0, validation_alias="DATABASE_CONNECT_TIMEOUT_SECONDS"
    )
    max_query_joins: int = Field(default=5, ge=0, validation_alias="MAX_QUERY_JOINS")
    max_query_nesting: int = Field(default=3, ge=0, validation_alias="MAX_QUERY_NESTING")
    max_repair_retries: int = Field(default=3, ge=0, validation_alias="MAX_REPAIR_RETRIES")
    enable_result_summary: bool = Field(default=True, validation_alias="ENABLE_RESULT_SUMMARY")
    llm_timeout_seconds: float = Field(default=30.0, gt=0, validation_alias="LLM_TIMEOUT_SECONDS")
    max_question_length: int = Field(
        default=2000, gt=0, le=10000, validation_alias="MAX_QUESTION_LENGTH"
    )
    max_conversation_context_chars: int = Field(
        default=2000, gt=0, le=10000, validation_alias="MAX_CONVERSATION_CONTEXT_CHARS"
    )
    max_request_body_bytes: int = Field(
        default=16384, gt=0, le=1048576, validation_alias="MAX_REQUEST_BODY_BYTES"
    )
    rate_limit_enabled: bool = Field(default=True, validation_alias="RATE_LIMIT_ENABLED")
    rate_limit_requests: int = Field(default=30, gt=0, validation_alias="RATE_LIMIT_REQUESTS")
    rate_limit_window_seconds: int = Field(
        default=60, gt=0, validation_alias="RATE_LIMIT_WINDOW_SECONDS"
    )

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be a standard logging level.")
        return normalized

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def effective_debug(self) -> bool:
        return self.debug and not self.is_production

    @property
    def effective_log_level(self) -> str:
        return "INFO" if self.is_production and self.log_level == "DEBUG" else self.log_level

    @model_validator(mode="after")
    def validate_production_configuration(self) -> Settings:
        if self.is_production:
            database_is_postgres = self.database_url.startswith("postgresql")
            analytics_database_is_postgres = self.analytics_database_url.startswith("postgresql")
            if not database_is_postgres or not analytics_database_is_postgres:
                raise ValueError("Production requires PostgreSQL application and analytics URLs.")
            if self.llm_mode == "mock":
                raise ValueError("The mock provider is disabled in production.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
