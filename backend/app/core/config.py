from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """The process cannot start with the supplied configuration.

    The message names each offending setting and the problem, never its value.
    """


class Settings(BaseSettings):
    database_url: str = Field(
        default="sqlite:///./app.db", validation_alias="DATABASE_URL", repr=False
    )
    analytics_database_url: str = Field(
        default="sqlite:///./analytics.db",
        validation_alias="ANALYTICS_DATABASE_URL",
        repr=False,
    )
    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias="GEMINI_API_KEY", repr=False
    )
    gemini_model: str = Field(default="gemini-2.5-flash", validation_alias="GEMINI_MODEL")
    llm_mode: Literal["mock", "gemini"] = Field(default="mock", validation_alias="LLM_MODE")
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
    rate_limit_llm_requests: int | None = Field(
        default=None, validation_alias="RATE_LIMIT_LLM_REQUESTS"
    )
    request_deadline_seconds: float = Field(
        default=25.0, gt=0, le=300, validation_alias="REQUEST_DEADLINE_SECONDS"
    )
    enable_direct_sql_endpoints: bool | None = Field(
        default=None, validation_alias="ENABLE_DIRECT_SQL_ENDPOINTS"
    )
    metrics_token: SecretStr | None = Field(
        default=None, validation_alias="METRICS_TOKEN", repr=False
    )
    auth_mode: Literal["jwt", "disabled"] = Field(default="disabled", validation_alias="AUTH_MODE")
    jwt_algorithm: Literal["HS256", "RS256", "ES256"] = Field(
        default="RS256", validation_alias="JWT_ALGORITHM"
    )
    jwt_secret: SecretStr | None = Field(default=None, validation_alias="JWT_SECRET", repr=False)
    jwt_public_key: SecretStr | None = Field(
        default=None, validation_alias="JWT_PUBLIC_KEY", repr=False
    )
    jwt_issuer: str | None = Field(default=None, validation_alias="JWT_ISSUER")
    jwt_audience: str | None = Field(default=None, validation_alias="JWT_AUDIENCE")

    app_version: str = Field(default="0.0.0-dev", validation_alias="APP_VERSION")

    # Durable conversations -------------------------------------------------------------------
    conversation_store: Literal["memory", "postgres"] = Field(
        default="memory", validation_alias="CONVERSATION_STORE"
    )
    conversation_ttl_days: int = Field(default=30, gt=0, validation_alias="CONVERSATION_TTL_DAYS")
    conversation_max_per_owner: int = Field(
        default=200, gt=0, validation_alias="CONVERSATION_MAX_PER_OWNER"
    )
    conversation_max_turns: int = Field(
        default=8, gt=0, le=100, validation_alias="CONVERSATION_MAX_TURNS"
    )

    # Query cost pre-flight (PostgreSQL planner cost units; unset disables it) ----------------
    query_cost_limit: float | None = Field(default=1_000_000.0, validation_alias="QUERY_COST_LIMIT")

    # Load-test support: simulated model latency for the mock provider (ignored in production,
    # where the mock provider is disabled).
    mock_llm_latency_ms: int = Field(
        default=0, ge=0, le=60_000, validation_alias="MOCK_LLM_LATENCY_MS"
    )
    mock_llm_jitter_ms: int = Field(
        default=0, ge=0, le=60_000, validation_alias="MOCK_LLM_JITTER_MS"
    )

    # Audit ------------------------------------------------------------------------
    audit_sink: Literal["log", "database", "both"] = Field(
        default="log", validation_alias="AUDIT_SINK"
    )
    audit_retention_days: int = Field(default=365, gt=0, validation_alias="AUDIT_RETENTION_DAYS")

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("rate_limit_llm_requests")
    @classmethod
    def validate_positive_optional(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("Value must be greater than zero.")
        return value

    @field_validator("query_cost_limit", mode="before")
    @classmethod
    def parse_query_cost_limit(cls, value: object) -> object:
        # An empty or "0"/"off" value disables the pre-flight; anything else must be positive.
        if value is None or (isinstance(value, str) and value.strip().casefold() in {"", "off"}):
            return None
        return value

    @field_validator("query_cost_limit")
    @classmethod
    def validate_query_cost_limit(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            return None
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
    def direct_sql_endpoints_enabled(self) -> bool:
        if self.enable_direct_sql_endpoints is None:
            return not self.is_production
        return self.enable_direct_sql_endpoints

    @property
    def effective_llm_rate_limit(self) -> int:
        """LLM-backed calls are limited more strictly than other analytics routes."""
        if self.rate_limit_llm_requests is not None:
            return self.rate_limit_llm_requests
        return min(self.rate_limit_requests, 20)

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
            if self.auth_mode != "jwt":
                raise ValueError("Production requires AUTH_MODE=jwt.")
        if self.auth_mode == "jwt":
            self._validate_jwt_configuration()
        if self.conversation_store == "postgres" and not self.database_url.startswith("postgresql"):
            raise ValueError("CONVERSATION_STORE=postgres requires a PostgreSQL DATABASE_URL.")
        if self.audit_sink in {"database", "both"} and not self.database_url.startswith(
            "postgresql"
        ):
            raise ValueError("AUDIT_SINK=database requires a PostgreSQL DATABASE_URL.")
        return self

    def _validate_jwt_configuration(self) -> None:
        if not self.jwt_issuer or not self.jwt_audience:
            raise ValueError("JWT_ISSUER and JWT_AUDIENCE are required when AUTH_MODE=jwt.")
        if self.jwt_algorithm == "HS256":
            if not (self.jwt_secret and len(self.jwt_secret.get_secret_value()) >= 32):
                raise ValueError("JWT_SECRET (at least 32 characters) is required for HS256.")
        elif not (self.jwt_public_key and self.jwt_public_key.get_secret_value().strip()):
            raise ValueError("JWT_PUBLIC_KEY is required for asymmetric JWT algorithms.")


# Settings that may be supplied as ``NAME_FILE=/path`` (Docker/Kubernetes secrets, a mounted
# secret-manager volume) instead of ``NAME=value``. Only secrets are listed: a value that ends up
# in an environment variable is visible to every process in the container and to `docker inspect`.
FILE_SECRETS: dict[str, str] = {
    "DATABASE_URL": "database_url",
    "ANALYTICS_DATABASE_URL": "analytics_database_url",
    "GEMINI_API_KEY": "gemini_api_key",
    "JWT_SECRET": "jwt_secret",
    "JWT_PUBLIC_KEY": "jwt_public_key",
    "METRICS_TOKEN": "metrics_token",
}


def read_secret_files(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Resolve ``*_FILE`` variables to setting values.

    Setting both ``NAME`` and ``NAME_FILE`` is an error rather than a silent precedence rule, so a
    rotated file secret can never be shadowed by a stale environment value.
    """
    environ = os.environ if environ is None else environ
    problems: list[str] = []
    values: dict[str, str] = {}
    for env_name, field_name in FILE_SECRETS.items():
        path = environ.get(f"{env_name}_FILE", "").strip()
        if not path:
            continue
        if environ.get(env_name, "").strip():
            problems.append(f"{env_name}: set either {env_name} or {env_name}_FILE, not both")
            continue
        try:
            contents = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            problems.append(f"{env_name}_FILE: the file is missing or unreadable")
            continue
        if not contents:
            problems.append(f"{env_name}_FILE: the file is empty")
            continue
        values[field_name] = contents
    if problems:
        raise ConfigurationError(_format_problems(problems))
    return values


def _format_problems(problems: list[str]) -> str:
    return "Invalid configuration:\n" + "\n".join(f"  - {problem}" for problem in problems)


def _describe_validation_error(error: ValidationError) -> str:
    aliases = {
        name: str(field.validation_alias or name) for name, field in Settings.model_fields.items()
    }
    problems = []
    for item in error.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in item["loc"])
        message = str(item["msg"]).removeprefix("Value error, ")
        label = aliases.get(location, location)
        problems.append(f"{label}: {message}" if label else message)
    return _format_problems(problems)


@lru_cache
def get_settings() -> Settings:
    """Load and validate configuration, failing with a precise, value-free message."""
    overrides: dict[str, Any] = dict(read_secret_files())
    try:
        return Settings(**overrides)
    except ValidationError as error:
        raise ConfigurationError(_describe_validation_error(error)) from None
