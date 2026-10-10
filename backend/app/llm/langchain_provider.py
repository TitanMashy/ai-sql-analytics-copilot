"""The application's model provider, backed by a LangChain chat model.

LangChain supplies provider integration and invocation only. What the model is asked (prompt
policy), how its answer is read (the structured-response contract in ``parser``), how failures are
named (``errors``), and when to retry or repair stay application-owned. Nothing here validates,
authorizes or executes SQL: the text this returns is untrusted and goes through the same SQLGlot
validation and read-only execution path as any other provider's, initial or repaired.

Retries: the underlying chat model is built with its own retries disabled (see ``factory``), so
this class applies the only transient-error retry in the model path. It is finite, retries only
infrastructure failures (``ClassifiedError.retryable``), and stops once ``retry_window_seconds``
has passed, so it cannot multiply with the repair loop or outlast the request deadline.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_tracing import stage, suspend_langchain_tracing
from app.core.metrics import metrics
from app.llm.errors import classify_provider_error
from app.llm.parser import parse_llm_response
from app.llm.prompt import SQLPromptBuilder
from app.llm.provider import LLMGeneration, LLMProviderError
from app.services.schema_retriever import SchemaContext

logger = logging.getLogger(__name__)


class ChatModel(Protocol):
    """The one capability used from a LangChain chat model."""

    def invoke(self, input: Any, *args: Any, **kwargs: Any) -> Any: ...


def _response_text(response: Any) -> str:
    """The text of a chat response, whether ``content`` is a string or a list of content blocks."""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts).strip()
    return ""


class LangChainSQLProvider:
    """SQL generation and repair through a configured LangChain chat model."""

    def __init__(
        self,
        *,
        name: str,
        label: str,
        model: str,
        chat_model: ChatModel,
        prompt_builder: SQLPromptBuilder | None = None,
        max_retries: int = 1,
        retry_window_seconds: float = 15.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name  # stable provider id used in metrics and responses ("gemini", "ollama")
        self.label = label  # display name used in messages
        self.model = model
        self.chat_model = chat_model
        self.prompt_builder = prompt_builder or SQLPromptBuilder()
        self.max_retries = max(0, max_retries)
        self.retry_window_seconds = retry_window_seconds
        self._sleep = sleep
        self._clock = clock

    def generate_sql(
        self,
        question: str,
        schema_context: SchemaContext,
        conversation_context: str | None = None,
    ) -> LLMGeneration:
        with stage("prompt_construction"):
            prompt = self.prompt_builder.build_user_prompt(
                question, schema_context, conversation_context
            )
        return self._complete(prompt)

    def repair_sql(
        self,
        question: str,
        original_sql: str,
        error_message: str,
        schema_context: SchemaContext,
        conversation_context: str | None = None,
    ) -> LLMGeneration:
        with stage("prompt_construction"):
            prompt = self.prompt_builder.build_repair_prompt(
                question, schema_context, original_sql, error_message, conversation_context
            )
        return self._complete(prompt)

    def _complete(self, prompt: str) -> LLMGeneration:
        messages = [
            SystemMessage(content=self.prompt_builder.system_instruction()),
            HumanMessage(content=prompt),
        ]
        response = self._invoke_with_retry(messages)
        with stage("response_parsing"):
            text = _response_text(response)
            if not text:
                raise LLMProviderError(
                    "INVALID_LLM_RESPONSE", f"{self.label} returned an empty response.", 502
                )
            # Malformed output is a classified failure, never something to guess into SQL.
            return parse_llm_response(text)

    def _invoke_with_retry(self, messages: list[Any]) -> Any:
        attempts = 1 + self.max_retries
        started_at = self._clock()
        for attempt in range(1, attempts + 1):
            retry = False
            with stage(
                "model_invocation",
                provider=self.name,
                model=self.model,
                attempt=attempt,
                max_attempts=attempts,
            ) as run:
                try:
                    # LangChain's automatic tracing would record the whole prompt and reply, so it
                    # is off for this call; the sanitized span above is the only record.
                    with suspend_langchain_tracing():
                        return self.chat_model.invoke(messages)
                except Exception as error:
                    classified = classify_provider_error(error, self.label)
                    run.fail(classified.code)
                    # Metadata only: no prompt, SQL, question, key, or provider message text.
                    logger.warning(
                        "LLM provider call failed",
                        extra={
                            "llm_provider": self.name,
                            "llm_model": self.model,
                            "error_code": classified.code,
                            "error_type": type(error).__name__,
                            "attempt": attempt,
                        },
                    )
                    in_window = self._clock() - started_at < self.retry_window_seconds
                    if classified.retryable and attempt < attempts and in_window:
                        retry = True
                    else:
                        message = classified.message
                        if classified.retryable and attempts > 1:
                            message = f"{message} It did not recover after {attempt} attempts."
                        raise LLMProviderError(
                            classified.code, message, classified.status_code
                        ) from error
            if retry:
                metrics.record_llm_retry(self.name)
                self._sleep(min(0.2 * 2 ** (attempt - 1), 2.0) + random.uniform(0, 0.1))
        raise AssertionError("unreachable: the loop always returns or raises")  # pragma: no cover
