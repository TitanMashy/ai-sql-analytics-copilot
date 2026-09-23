import logging

from openai import OpenAI

from app.core.config import Settings
from app.llm.parser import parse_llm_response
from app.llm.prompt import SQLPromptBuilder
from app.llm.provider import LLMGeneration, LLMProviderError
from app.services.schema_retriever import SchemaContext

logger = logging.getLogger(__name__)


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings, prompt_builder: SQLPromptBuilder | None = None) -> None:
        if not settings.openai_api_key:
            raise LLMProviderError(
                "LLM_CONFIGURATION_ERROR",
                "OPENAI_API_KEY is required when LLM_MODE is openai.",
                503,
            )
        self.client = OpenAI(
            api_key=settings.openai_api_key, timeout=settings.query_timeout_seconds
        )
        self.model = settings.openai_model
        self.prompt_builder = prompt_builder or SQLPromptBuilder()

    def generate_sql(
        self,
        question: str,
        schema_context: SchemaContext,
        conversation_context: str | None = None,
    ) -> LLMGeneration:
        prompt = self.prompt_builder.build(question, schema_context, conversation_context)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Return only the requested JSON object. Do not execute SQL.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                raise LLMProviderError(
                    "INVALID_LLM_RESPONSE",
                    "The LLM returned an empty response.",
                    502,
                )
            return parse_llm_response(content)
        except LLMProviderError:
            raise
        except Exception as error:
            logger.exception("OpenAI SQL generation failed")
            raise LLMProviderError(
                "LLM_PROVIDER_ERROR",
                "The configured LLM provider could not generate SQL.",
                502,
            ) from error
