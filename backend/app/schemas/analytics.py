from typing import Any

from pydantic import BaseModel, Field


class AnalyticsQueryRequest(BaseModel):
    sql: str = Field(description="A single read-only SELECT statement.")


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


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
