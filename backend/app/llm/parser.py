import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.llm.provider import LLMGeneration, LLMProviderError


class StructuredLLMResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sql: str = Field(min_length=1)
    explanation: str = ""
    tables_used: list[str] = Field(default_factory=list)
    confidence: float | None = None


def _strip_code_fence(content: str) -> str:
    fenced = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", content, re.IGNORECASE | re.DOTALL)
    return fenced.group(1) if fenced else content.strip()


def parse_llm_response(content: str | dict[str, Any]) -> LLMGeneration:
    try:
        payload = json.loads(_strip_code_fence(content)) if isinstance(content, str) else content
        parsed = StructuredLLMResponse.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
        raise LLMProviderError(
            "INVALID_LLM_RESPONSE",
            "The LLM returned malformed or incomplete structured output.",
            502,
        ) from error

    if not parsed.sql.strip():
        raise LLMProviderError("INVALID_LLM_RESPONSE", "The LLM returned empty SQL.", 502)
    return LLMGeneration(
        sql=parsed.sql.strip(),
        explanation=parsed.explanation.strip(),
        tables_used=parsed.tables_used,
        confidence=parsed.confidence,
    )
