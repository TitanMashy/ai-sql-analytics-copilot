import logging
from typing import Any

from google import genai
from google.genai import errors, types

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
        api_key = (
            settings.gemini_api_key.get_secret_value()
            if settings.gemini_api_key
            else ""
        )
        if not api_key.strip() and client is None:
            raise LLMProviderError(
                "LLM_CONFIGURATION_ERROR",
                "GEMINI_API_KEY is required when LLM_MODE is gemini.",
                503,
            )
        self.client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=round(settings.llm_timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(
                    attempts=3,
                    initial_delay=0.2,
                    max_delay=2.0,
                    exp_base=2.0,
                    jitter=0.2,
                    http_status_codes=[500, 502, 503, 504],
                ),
            ),
        )
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
        except errors.APIError as error:
            status_code = int(error.code)
            logger.warning(
                "Gemini provider request failed",
                extra={"provider_status_code": status_code},
            )
            if status_code == 429:
                raise LLMProviderError(
                    "LLM_RATE_LIMITED",
                    "The configured Gemini provider is temporarily rate limited.",
                    503,
                ) from error
            if status_code == 404:
                raise LLMProviderError(
                    "LLM_MODEL_UNAVAILABLE",
                    "The configured Gemini model is unavailable.",
                    503,
                ) from error
            if status_code == 504:
                raise LLMProviderError(
                    "LLM_TIMEOUT",
                    "The Gemini request exceeded its configured timeout.",
                    504,
                ) from error
            if status_code >= 500:
                raise LLMProviderError(
                    "LLM_PROVIDER_UNAVAILABLE",
                    "The Gemini provider is temporarily unavailable.",
                    503,
                ) from error
            raise LLMProviderError(
                "LLM_PROVIDER_ERROR",
                "The configured Gemini provider could not generate SQL.",
                502,
            ) from error
        except Exception as error:
            if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.casefold():
                logger.warning("Gemini provider request timed out")
                raise LLMProviderError(
                    "LLM_TIMEOUT",
                    "The Gemini request exceeded its configured timeout.",
                    504,
                ) from error
            logger.warning(
                "Gemini provider request failed",
                extra={"error_type": type(error).__name__},
            )
            raise LLMProviderError(
                "LLM_PROVIDER_ERROR",
                "The configured Gemini provider could not generate SQL.",
                502,
            ) from error
