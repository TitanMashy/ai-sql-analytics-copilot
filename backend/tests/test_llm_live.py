"""Opt-in checks against real model providers. Skipped unless explicitly enabled.

    RUN_LIVE_LLM_TESTS=1 GEMINI_API_KEY=... python -m pytest tests/test_llm_live.py -m live -v
    RUN_LIVE_LLM_TESTS=1 LLM_MODEL=<ollama model> python -m pytest \
        tests/test_llm_live.py -m live -k ollama -v

The default suite never calls an external service. These tests do, so they spend provider quota
or local compute and need a key or a running Ollama. A test whose prerequisite is missing is
*skipped with the reason*, never reported as passing.
"""

import os

import httpx
import pytest

from app.analytics.validator import SQLValidator
from app.core.config import Settings
from app.llm.factory import build_llm_provider
from app.services.schema_retriever import SchemaRetriever

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_LLM_TESTS") != "1",
        reason="live provider checks are opt-in: set RUN_LIVE_LLM_TESTS=1",
    ),
]

QUESTION = "How many active vehicles do we have?"


def _check_generation(provider) -> None:
    context = SchemaRetriever().retrieve(QUESTION)

    generated = provider.generate_sql(QUESTION, context)

    # Parsed and structured; the same validator as every other provider decides if it may run.
    assert generated.sql.lstrip().upper().startswith(("SELECT", "WITH"))
    result = SQLValidator().validate(generated.sql)
    assert result.valid, result.errors


def test_live_gemini_generates_valid_sql() -> None:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key.strip():
        pytest.skip("GEMINI_API_KEY is not set")
    settings = Settings(
        llm_provider="gemini", gemini_api_key=key, llm_model=os.environ.get("LLM_MODEL") or None
    )

    _check_generation(build_llm_provider(settings))


def test_live_ollama_generates_valid_sql() -> None:
    model = os.environ.get("LLM_MODEL", "").strip()
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    if not model:
        pytest.skip("LLM_MODEL is not set (the Ollama model to test, for example one you pulled)")
    try:
        httpx.get(f"{base_url}/api/tags", timeout=3).raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"Ollama is not reachable at {base_url}")
    settings = Settings(llm_provider="ollama", llm_model=model, ollama_base_url=base_url)

    _check_generation(build_llm_provider(settings))
