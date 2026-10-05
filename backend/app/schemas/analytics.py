from typing import Any

from pydantic import BaseModel, Field


class AnalyticsQueryRequest(BaseModel):
    sql: str = Field(
        max_length=12000,
        description="A single read-only SELECT statement.",
    )


class AnalyticsValidationResponse(BaseModel):
    valid: bool
    normalized_sql: str | None
    errors: list[str]
    warnings: list[str]
    tables: list[str]
    complexity: dict[str, Any]


class AnalyticsQueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    execution_time_ms: float
    truncated: bool = False


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    debug: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
