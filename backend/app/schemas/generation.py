from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings


class GenerationRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=10000,
        description="A natural-language analytics question.",
    )
    conversation_id: str | None = Field(
        default=None, max_length=128, description="Optional conversation thread."
    )
    conversation_context: str | None = Field(
        default=None, max_length=10000, description="Optional prior context."
    )

    @field_validator("question")
    @classmethod
    def enforce_question_limit(cls, value: str) -> str:
        if len(value) > get_settings().max_question_length:
            raise ValueError("Question exceeds the configured length limit.")
        return value

    @field_validator("conversation_context")
    @classmethod
    def enforce_context_limit(cls, value: str | None) -> str | None:
        if value and len(value) > get_settings().max_conversation_context_chars:
            raise ValueError("Conversation context exceeds the configured length limit.")
        return value


class GeneratedQueryResponse(BaseModel):
    question: str
    sql: str
    explanation: str
    tables_used: list[str]
    schema_context: list[str]
    provider: str
    confidence: float | None = None


class AskResponse(GeneratedQueryResponse):
    request_id: str | None = None
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    execution_time_ms: float
    truncated: bool = False
    summary: str | None = None
    kpi: KPIResponse | None = None
    visualization: VisualizationResponse | None = None
    warnings: list[str] = Field(default_factory=list)


class KPIResponse(BaseModel):
    label: str
    value: Any
    format: Literal["currency", "integer", "decimal", "percentage", "text"]


class VisualizationAxisResponse(BaseModel):
    field: str
    format: Literal["currency", "integer", "decimal", "percentage", "text"] = "text"


class VisualizationResponse(BaseModel):
    type: Literal["table", "kpi", "bar", "line", "area", "pie"]
    title: str
    x_axis: VisualizationAxisResponse | None = None
    y_axis: VisualizationAxisResponse | None = None
    series: list[VisualizationAxisResponse] = Field(default_factory=list)
