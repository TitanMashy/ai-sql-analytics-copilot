from __future__ import annotations

from typing import Any, Literal

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
