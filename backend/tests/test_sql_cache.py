import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.analytics.service import AnalyticsQueryService
from app.core.auth import ANALYTICS_ADMIN_ROLE, Principal
from app.core.metrics import metrics
from app.llm.mock_provider import MockLLMProvider
from app.services.generation import SQLGenerationService
from app.services.sql_cache import CachedSql, SqlCache, normalize_question, tenant_key

QUESTION = "How many active vehicles do we have?"


class CountingProvider(MockLLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.generate_calls = 0

    def generate_sql(self, question, schema_context, conversation_context=None):
        self.generate_calls += 1
        return super().generate_sql(question, schema_context, conversation_context)


def _analytics() -> AnalyticsQueryService:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE vehicles (id INTEGER, status TEXT)"))
        connection.execute(text("INSERT INTO vehicles VALUES (1, 'active'), (2, 'inactive')"))
    return AnalyticsQueryService(engine)


def _service(cache: SqlCache | None, provider: CountingProvider | None = None):
    provider = provider or CountingProvider()
    service = SQLGenerationService(
        provider,
        analytics_service=_analytics(),
        sql_cache=cache,
        schema_version="schema-v1",
    )
    return service, provider


def test_question_normalization_ignores_case_spacing_and_trailing_punctuation() -> None:
    assert normalize_question("  How MANY   active vehicles?? ") == "how many active vehicles"
    assert normalize_question("How many active vehicles.") == normalize_question(
        "how many active vehicles"
    )


def test_tenant_keys_separate_customers_and_admins() -> None:
    admin = Principal("a", roles=(ANALYTICS_ADMIN_ROLE,))
    customer_one = Principal("u1", customer_id=1)
    customer_two = Principal("u2", customer_id=2)

    assert tenant_key(admin) == "global"
    assert tenant_key(customer_one) != tenant_key(customer_two)
    assert tenant_key(None) == "none"
    assert SqlCache.key(QUESTION, "v1", customer_one) != SqlCache.key(QUESTION, "v1", customer_two)
    assert SqlCache.key(QUESTION, "v1", customer_one) != SqlCache.key(QUESTION, "v2", customer_one)


def test_a_repeat_question_skips_the_llm_call_and_still_runs_the_sql() -> None:
    service, provider = _service(SqlCache())
    hits_before = metrics.snapshot()["sql_cache_hits_total"]
    misses_before = metrics.snapshot()["sql_cache_misses_total"]

    first = service.ask(QUESTION)
    second = service.ask(QUESTION)

    assert provider.generate_calls == 1
    assert first.generated.sql == second.generated.sql
    assert second.result.rows == [{"active_vehicle_count": 1}]  # executed again, not replayed
    assert metrics.snapshot()["sql_cache_misses_total"] == misses_before + 1
    assert metrics.snapshot()["sql_cache_hits_total"] == hits_before + 1


def test_the_cache_is_off_unless_configured() -> None:
    service, provider = _service(None)

    service.ask(QUESTION)
    service.ask(QUESTION)

    assert provider.generate_calls == 2


def test_cache_entries_are_per_tenant() -> None:
    service, provider = _service(SqlCache())
    customer_one = Principal("u1", customer_id=1, roles=("analyst",))
    customer_two = Principal("u2", customer_id=2, roles=("analyst",))

    service.ask(QUESTION, principal=customer_one)
    service.ask(QUESTION, principal=customer_two)
    service.ask(QUESTION, principal=customer_one)

    assert provider.generate_calls == 2  # customer two did not reuse customer one's entry


def test_follow_ups_with_conversation_context_are_never_cached() -> None:
    service, provider = _service(SqlCache())

    service.ask(QUESTION, conversation_context="user: earlier\nassistant: an answer")
    service.ask(QUESTION, conversation_context="user: earlier\nassistant: an answer")

    assert provider.generate_calls == 2


def test_a_new_schema_version_invalidates_entries() -> None:
    cache = SqlCache()
    first, provider = _service(cache)
    first.ask(QUESTION)
    second = SQLGenerationService(
        provider,
        analytics_service=_analytics(),
        sql_cache=cache,
        schema_version="schema-v2",
    )

    second.ask(QUESTION)

    assert provider.generate_calls == 2


def test_failed_answers_are_not_cached() -> None:
    cache = SqlCache()
    service, _ = _service(cache)

    with pytest.raises(Exception):  # noqa: B017 - the mock cannot answer this question
        service.ask("something the mock provider cannot answer")

    assert len(cache) == 0


def test_cached_sql_that_starts_failing_is_discarded() -> None:
    cache = SqlCache()
    service, provider = _service(cache)
    key = SqlCache.key(QUESTION, "schema-v1", None)
    cache.put(
        key,
        CachedSql(
            sql="SELECT missing_column FROM vehicles",
            explanation="stale",
            tables_used=("vehicles",),
            confidence=None,
            provider="mock",
        ),
    )

    result = service.ask(QUESTION)

    # The stale entry failed validation, was repaired by the provider, and was replaced.
    assert result.result.rows == [{"active_vehicle_count": 1}]
    assert cache.get(key).sql != "SELECT missing_column FROM vehicles"
    assert provider.repair_hints  # the repair step ran


def test_entries_expire_and_the_cache_is_bounded() -> None:
    cache = SqlCache(ttl_seconds=0.05, max_entries=2)
    value = CachedSql("SELECT 1", "x", (), None, "mock")
    cache.put(("a", "v", "t"), value)
    cache.put(("b", "v", "t"), value)
    cache.put(("c", "v", "t"), value)

    assert len(cache) == 2
    assert cache.get(("a", "v", "t")) is None  # least recently used was evicted
    time.sleep(0.08)
    assert cache.get(("c", "v", "t")) is None  # expired
