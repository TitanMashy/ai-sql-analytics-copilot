"""Select and build the configured model provider.

This is the only place that chooses a provider and the only place that constructs provider
clients. Routes and services depend on the ``LLMProvider`` protocol and never on LangChain or a
vendor SDK. Selection is explicit (``LLM_PROVIDER``): an unsupported or misconfigured provider
fails with a clear error, and nothing ever falls back to a different provider, because a silent
switch from a local model to a cloud one would send data somewhere the operator did not choose.

Provider clients are imported lazily so that mock mode, tests and CI never import (or need) a
vendor integration they are not using.
"""

from __future__ import annotations

from app.core.config import Settings
from app.llm.langchain_provider import ChatModel, LangChainSQLProvider
from app.llm.mock_provider import MockLLMProvider
from app.llm.provider import LLMProvider, LLMProviderError

SUPPORTED_PROVIDERS = ("mock", "gemini", "ollama")


def _configuration_error(message: str) -> LLMProviderError:
    return LLMProviderError("LLM_CONFIGURATION_ERROR", message, 503)


def build_chat_model(settings: Settings) -> ChatModel:
    """Construct the LangChain chat model for ``settings.llm_provider`` (not the mock)."""
    provider = settings.llm_provider
    model = settings.effective_llm_model
    timeout = settings.llm_timeout_seconds

    if provider == "gemini":
        api_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
        if not api_key.strip():
            raise _configuration_error("GEMINI_API_KEY is required when LLM_PROVIDER is gemini.")
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=0.0,
            timeout=timeout,
            # LangChain retries 6 times by default. Retries are applied once, in
            # LangChainSQLProvider, so they cannot multiply with the repair loop.
            max_retries=0,
            response_mime_type="application/json",
        )

    if provider == "ollama":
        if not model:
            raise _configuration_error("LLM_MODEL is required when LLM_PROVIDER is ollama.")
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model,
            base_url=settings.ollama_base_url,
            temperature=0.0,
            format="json",
            # Never pull a model implicitly; a missing model is reported as unavailable.
            validate_model_on_init=False,
            client_kwargs={"timeout": timeout},
        )

    raise _configuration_error(
        f"LLM_PROVIDER must be one of {', '.join(SUPPORTED_PROVIDERS)}; chat models are built "
        "only for gemini and ollama."
    )


def build_llm_provider(settings: Settings) -> LLMProvider:
    """Build the provider selected by ``LLM_PROVIDER``."""
    provider = settings.llm_provider

    if provider == "mock":
        if settings.is_production:
            raise _configuration_error("The mock provider is disabled in production.")
        return MockLLMProvider(
            latency_ms=settings.mock_llm_latency_ms, jitter_ms=settings.mock_llm_jitter_ms
        )

    if provider in {"gemini", "ollama"}:
        return LangChainSQLProvider(
            name=provider,
            label="Gemini" if provider == "gemini" else "Ollama",
            model=settings.effective_llm_model or "",
            chat_model=build_chat_model(settings),
            max_retries=settings.llm_max_retries,
            # Retrying must not outlast the request: stop well inside the overall deadline.
            retry_window_seconds=min(
                settings.llm_timeout_seconds, settings.request_deadline_seconds
            )
            / 2,
        )

    raise _configuration_error(f"LLM_PROVIDER must be one of {', '.join(SUPPORTED_PROVIDERS)}.")
