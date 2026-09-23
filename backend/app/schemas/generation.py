from typing import Any

from pydantic import BaseModel, Field


class GenerationRequest(BaseModel):
    question: str = Field(description="A natural-language analytics question.")
    conversation_context: str | None = Field(default=None, description="Optional prior context.")


class GeneratedQueryResponse(BaseModel):
    question: str
    sql: str
    explanation: str
    tables_used: list[str]
    schema_context: list[str]
    provider: str
    confidence: float | None = None


class AskResponse(GeneratedQueryResponse):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    execution_time_ms: float
