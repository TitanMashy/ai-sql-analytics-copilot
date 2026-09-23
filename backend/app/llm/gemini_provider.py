import logging
from typing import Any

from google import genai
from google.genai import types

from app.core.config import Settings
from app.llm.parser import StructuredLLMResponse, parse_llm_response
from app.llm.prompt import SQLPromptBuilder
from app.llm.provider import LLMGeneration, LLMProviderError
from app.services.schema_retriever import SchemaContext

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Google Gemini implementation of the shared SQL generation provider."""

    name = "gemini"

    def __init__(
        self,
        settings: Settings,
        prompt_builder: SQLPromptBuilder | None = None,
        client: Any | None = None,
    ) -> None:
        if not settings.gemini_api_key and client is None:
            raise LLMProviderError(
                "LLM_CONFIGURATION_ERROR",
                "GEMINI_API_KEY is required when LLM_MODE is gemini.",
                503,
            )
        self.client = client or genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model
        self.prompt_builder = prompt_builder or SQLPromptBuilder()

    def generate_sql(
        self,
        question: str,
        schema_context: SchemaContext,
        conversation_context: str | None = None,
    ) -> LLMGeneration:
        prompt = self.prompt_builder.build(question, schema_context, conversation_context)
        return self._complete(prompt)

    def repair_sql(
        self,
        question: str,
        original_sql: str,
        error_message: str,
        schema_context: SchemaContext,
    ) -> LLMGeneration:
        prompt = self.prompt_builder.build(question, schema_context)
        repair_prompt = (
            f"{prompt}\nRepair the SQL below using the database error. "
            "Return the same JSON structure and only a read-only SELECT.\n"
            f"Original SQL:\n{original_sql}\nDatabase error:\n{error_message}"
        )
        return self._complete(repair_prompt)

    def _complete(self, prompt: str) -> LLMGeneration:
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=StructuredLLMResponse,
                ),
            )
            content = getattr(response, "text", None)
            if not content:
                raise LLMProviderError(
                    "INVALID_LLM_RESPONSE",
                    "Gemini returned an empty response.",
                    502,
                )
            return parse_llm_response(content)
        except LLMProviderError:
            raise
        except Exception as error:
            logger.exception("Gemini SQL generation failed")
            raise LLMProviderError(
                "LLM_PROVIDER_ERROR",
                "The configured Gemini provider could not generate SQL.",
                502,
            ) from error
