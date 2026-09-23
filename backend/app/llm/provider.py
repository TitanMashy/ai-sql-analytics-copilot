from dataclasses import dataclass
from typing import Protocol

from app.services.schema_retriever import SchemaContext


@dataclass(frozen=True)
class LLMGeneration:
    sql: str
    explanation: str
    tables_used: list[str]
    confidence: float | None = None


class LLMProviderError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class LLMProvider(Protocol):
    name: str

    def generate_sql(
        self,
        question: str,
        schema_context: SchemaContext,
        conversation_context: str | None = None,
    ) -> LLMGeneration: ...

    def repair_sql(
        self,
        question: str,
        original_sql: str,
        error_message: str,
        schema_context: SchemaContext,
    ) -> LLMGeneration: ...
