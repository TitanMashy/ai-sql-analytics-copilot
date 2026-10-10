"""Smoke test for the configured model provider.

    python scripts/llm_smoke.py
    python scripts/llm_smoke.py --question "How many active vehicles do we have?"

Uses the same settings as the backend (``LLM_PROVIDER``, ``LLM_MODEL``, ``GEMINI_API_KEY``,
``OLLAMA_BASE_URL``, ...), so it tests exactly what the application would run. It checks, in order:

1. the provider can be built from the configuration;
2. the model answers and the reply parses into the structured SQL contract;
3. the SQL passes the same SQLGlot validation as every other provider's;
4. when ``ANALYTICS_DATABASE_URL`` points at PostgreSQL, the SQL runs through the read-only,
   tenant-scoped executor (as an administrator, so it sees all demo data).

It prints one line per step and exits 0 only if every step that ran passed. It never prints keys.
No model is downloaded and no provider is started by this script.
"""

import argparse
import time

DEFAULT_QUESTION = "How many active vehicles do we have?"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test the configured model provider.")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    arguments = parser.parse_args(argv)

    from app.analytics.dependencies import get_analytics_query_service
    from app.analytics.validator import SQLValidator
    from app.core.auth import ANALYTICS_ADMIN_ROLE, Principal
    from app.core.config import ConfigurationError, get_settings
    from app.core.llm_tracing import configure_llm_tracing, flush_llm_tracing
    from app.llm.factory import build_llm_provider
    from app.llm.provider import LLMProviderError
    from app.services.schema_retriever import SchemaRetriever

    try:
        settings = get_settings()
    except ConfigurationError as error:
        print(f"FAIL configuration: {error}")
        return 2
    configure_llm_tracing(settings)
    model = settings.effective_llm_model or "-"
    where = f" at {settings.ollama_base_url}" if settings.llm_provider == "ollama" else ""
    print(f"provider={settings.llm_provider} model={model}{where}")

    try:
        provider = build_llm_provider(settings)
    except LLMProviderError as error:
        print(f"FAIL build provider: {error.code}: {error.message}")
        return 2
    print("ok   provider built")

    context = SchemaRetriever().retrieve(arguments.question)
    started = time.perf_counter()
    try:
        generated = provider.generate_sql(arguments.question, context)
    except LLMProviderError as error:
        print(f"FAIL model call: {error.code}: {error.message}")
        return 1
    elapsed = time.perf_counter() - started
    print(f"ok   model answered and the reply parsed ({elapsed:.1f}s)")
    print(f"     sql: {generated.sql}")

    validation = SQLValidator(max_result_rows=settings.max_result_rows).validate(generated.sql)
    if not validation.valid:
        print(f"FAIL validation: {'; '.join(validation.errors)}")
        return 1
    print("ok   the SQL passed validation")

    status = 0
    if settings.analytics_database_url.startswith("postgresql"):
        principal = Principal("llm-smoke", roles=(ANALYTICS_ADMIN_ROLE,))
        try:
            result = get_analytics_query_service().execute(generated.sql, principal=principal)
        except Exception as error:  # noqa: BLE001 - any failure is the result of this step
            print(f"FAIL execution: {getattr(error, 'code', type(error).__name__)}")
            status = 1
        else:
            print(f"ok   executed read-only: {result.row_count} row(s), columns {result.columns}")
    else:
        print("skip execution: ANALYTICS_DATABASE_URL is not PostgreSQL")

    flush_llm_tracing(3)
    print("PASS" if status == 0 else "FAIL")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
