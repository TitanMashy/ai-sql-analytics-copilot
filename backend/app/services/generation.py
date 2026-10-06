import contextvars
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, replace
from functools import partial
from time import perf_counter

from app.analytics.service import AnalyticsQueryService, AnalyticsServiceError, QueryResult
from app.conversation.service import ConversationStore, get_conversation_memory
from app.core.auth import Principal
from app.core.deadline import Deadline
from app.core.metrics import metrics
from app.core.telemetry import get_request_telemetry
from app.core.tracing import record_span_error, span
from app.llm.prompt import SQLPromptBuilder
from app.llm.provider import LLMGeneration, LLMProvider, LLMProviderError
from app.services.result_analyzer import AnalyticsResultAnalyzer
from app.services.result_models import ResultAnalysis
from app.services.result_summary import ResultSummaryService
from app.services.schema_retriever import SchemaContext, SchemaRetriever
from app.services.sql_cache import CachedSql, SqlCache
from app.services.visualization import VisualizationSelector

logger = logging.getLogger(__name__)

GENERATION_FAILED_MESSAGE = (
    "I couldn't produce a valid query for that question. Try rephrasing it, or ask about a "
    "specific fleet, revenue, or maintenance metric."
)
DEADLINE_MESSAGE = (
    "The request took too long to complete. Please try again or simplify the question."
)

# Provider SDK calls are blocking. Running them on worker threads lets the request enforce its
# own deadline instead of waiting out a slow provider (and its internal retries).
_provider_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="llm-call")


@dataclass(frozen=True)
class GeneratedQuery:
    question: str
    sql: str
    explanation: str
    tables_used: list[str]
    schema_context: list[str]
    provider: str
    confidence: float | None


@dataclass(frozen=True)
class AskedQuery:
    generated: GeneratedQuery
    result: QueryResult
    analysis: ResultAnalysis
    summary: str | None


class SQLGenerationService:
    def __init__(
        self,
        provider: LLMProvider,
        retriever: SchemaRetriever | None = None,
        prompt_builder: SQLPromptBuilder | None = None,
        analytics_service: AnalyticsQueryService | None = None,
        max_repair_retries: int = 3,
        result_analyzer: AnalyticsResultAnalyzer | None = None,
        visualization_selector: VisualizationSelector | None = None,
        summary_service: ResultSummaryService | None = None,
        conversation_memory: ConversationStore | None = None,
        request_deadline_seconds: float | None = None,
        sql_cache: SqlCache | None = None,
        schema_version: str = "",
    ) -> None:
        self.provider = provider
        self.retriever = retriever or SchemaRetriever()
        self.prompt_builder = prompt_builder or SQLPromptBuilder()
        self.analytics_service = analytics_service
        self.max_repair_retries = max_repair_retries
        self.result_analyzer = result_analyzer or AnalyticsResultAnalyzer()
        self.visualization_selector = visualization_selector or VisualizationSelector()
        self.summary_service = summary_service or ResultSummaryService()
        self.conversation_memory = conversation_memory or get_conversation_memory()
        self.request_deadline_seconds = request_deadline_seconds
        self.sql_cache = sql_cache
        self.schema_version = schema_version

    def generate(
        self,
        question: str,
        conversation_context: str | None = None,
        conversation_id: str | None = None,
        principal: Principal | None = None,
    ) -> GeneratedQuery:
        deadline = Deadline(self.request_deadline_seconds)
        context, resolved_context = self._prepare(
            question, conversation_context, conversation_id, principal
        )
        return self._generate(question, context, resolved_context, deadline)

    def ask(
        self,
        question: str,
        request_id: str | None = None,
        conversation_context: str | None = None,
        conversation_id: str | None = None,
        principal: Principal | None = None,
    ) -> AskedQuery:
        if self.analytics_service is None:
            raise RuntimeError("AnalyticsQueryService is required for ask")
        deadline = Deadline(self.request_deadline_seconds)
        context, resolved_context = self._prepare(
            question, conversation_context, conversation_id, principal
        )
        cache_key = self._cache_key(question, resolved_context, principal)
        generated = self._cached_query(cache_key, question, context)
        from_cache = generated is not None
        if generated is None:
            generated = self._generate(question, context, resolved_context, deadline)
        telemetry = get_request_telemetry()
        repair_attempts = 0
        while True:
            try:
                self._check_deadline(deadline)
                result = self.analytics_service.execute(
                    generated.sql,
                    request_id=request_id,
                    principal=principal,
                    timeout_seconds=deadline.remaining(),
                )
                analysis = self.result_analyzer.analyze(
                    question=question,
                    sql=generated.sql,
                    columns=result.columns,
                    rows=result.rows,
                    execution_time_ms=result.execution_time_ms,
                    row_count=result.row_count,
                    column_types=result.column_types,
                )
                visualization = self.visualization_selector.select(
                    question, result.columns, result.rows, analysis
                )
                warnings = list(analysis.warnings)
                if result.truncated:
                    warnings.append(
                        f"Results were truncated to the first {result.row_count:,} rows; "
                        "refine the question for complete results."
                    )
                analysis = replace(analysis, visualization=visualization, warnings=warnings)
                summary = self.summary_service.summarize(
                    question, generated.sql, result.columns, result.rows, analysis
                )
                if cache_key is not None and self.sql_cache is not None:
                    self.sql_cache.put(
                        cache_key,
                        CachedSql(
                            sql=generated.sql,
                            explanation=generated.explanation,
                            tables_used=tuple(generated.tables_used),
                            confidence=generated.confidence,
                            provider=generated.provider,
                        ),
                    )
                if conversation_id:
                    self._remember(conversation_id, question, generated, summary, principal)
                if repair_attempts:
                    metrics.increment("sql_repair_successes_total")
                    logger.info(
                        "analytics SQL repair succeeded",
                        extra={"request_id": request_id, "repair_count": repair_attempts},
                    )
                return AskedQuery(
                    generated=generated,
                    result=result,
                    analysis=analysis,
                    summary=summary,
                )
            except AnalyticsServiceError as error:
                if from_cache and cache_key is not None and self.sql_cache is not None:
                    # Never replay cached SQL that just failed; a repair or a fresh answer
                    # replaces it.
                    self.sql_cache.discard(cache_key)
                    from_cache = False
                if not error.repairable:
                    raise
                if repair_attempts >= self.max_repair_retries:
                    raise self._generation_failed(generated, error) from error
                repair_attempts += 1
                metrics.increment("sql_repair_attempts_total")
                if telemetry:
                    telemetry.repair_count = repair_attempts
                logger.info(
                    "repairing analytics SQL",
                    extra={"request_id": request_id, "repair_count": repair_attempts},
                )
                # The hint carries the identifier or SQLSTATE detail that makes a repair possible;
                # the public message is deliberately generic and would turn repair into a re-roll.
                repair_call = partial(
                    self.provider.repair_sql,
                    question,
                    generated.sql,
                    error.repair_hint or error.message,
                    context,
                    conversation_context=resolved_context,
                )
                repaired = self._call_provider(repair_call, deadline)
                generated = self._to_generated_query(question, context, repaired)

    # -- prompt-to-SQL cache -----------------------------------------------------------------

    def _cache_key(
        self, question: str, resolved_context: str | None, principal: Principal | None
    ) -> tuple[str, str, str] | None:
        """A cache key for standalone questions only (follow-ups depend on their context)."""
        if self.sql_cache is None:
            return None
        if resolved_context and resolved_context != "No prior conversation context.":
            return None
        return self.sql_cache.key(question, self.schema_version, principal)

    def _cached_query(
        self,
        cache_key: tuple[str, str, str] | None,
        question: str,
        context: SchemaContext,
    ) -> GeneratedQuery | None:
        if cache_key is None or self.sql_cache is None:
            return None
        cached = self.sql_cache.get(cache_key)
        metrics.record_cache(cached is not None)
        if cached is None:
            return None
        return GeneratedQuery(
            question=question,
            sql=cached.sql,
            explanation=cached.explanation,
            tables_used=list(cached.tables_used),
            schema_context=context.table_names,
            provider=cached.provider,
            confidence=cached.confidence,
        )

    # -- pipeline steps ---------------------------------------------------------------------

    def _prepare(
        self,
        question: str,
        conversation_context: str | None,
        conversation_id: str | None,
        principal: Principal | None,
    ) -> tuple[SchemaContext, str | None]:
        if not question.strip():
            raise LLMProviderError("INVALID_REQUEST", "Question cannot be empty.", 422)
        telemetry = get_request_telemetry()
        if telemetry:
            telemetry.conversation_id = conversation_id
        owner = principal.user_id if principal else None
        if conversation_id:
            # Raises ConversationAccessError for a conversation owned by someone else.
            self.conversation_memory.assert_access(conversation_id, owner)
        resolved_context = self._resolve_context(conversation_id, conversation_context, owner)
        return self.retriever.retrieve(question, resolved_context), resolved_context

    def _generate(
        self,
        question: str,
        context: SchemaContext,
        resolved_context: str | None,
        deadline: Deadline,
    ) -> GeneratedQuery:
        generation = self._call_provider(
            lambda: self.provider.generate_sql(question, context, resolved_context), deadline
        )
        return self._to_generated_query(question, context, generation)

    def _remember(
        self,
        conversation_id: str,
        question: str,
        generated: GeneratedQuery,
        summary: str | None,
        principal: Principal | None,
    ) -> None:
        """Record a completed exchange. Failed attempts are never stored."""
        owner = principal.user_id if principal else None
        self.conversation_memory.add_turn(conversation_id, "user", question, owner=owner)
        self.conversation_memory.add_turn(
            conversation_id,
            "assistant",
            summary or generated.explanation or "The SQL executed successfully.",
            owner=owner,
            sql=generated.sql,
            tables=generated.tables_used,
        )

    @staticmethod
    def _check_deadline(deadline: Deadline) -> None:
        if deadline.expired():
            raise SQLGenerationService._deadline_error()

    @staticmethod
    def _deadline_error() -> AnalyticsServiceError:
        metrics.increment("deadline_exceeded_total")
        return AnalyticsServiceError("REQUEST_DEADLINE_EXCEEDED", DEADLINE_MESSAGE, 504)

    @staticmethod
    def _generation_failed(
        generated: GeneratedQuery, error: AnalyticsServiceError
    ) -> AnalyticsServiceError:
        return AnalyticsServiceError(
            "QUERY_GENERATION_FAILED",
            GENERATION_FAILED_MESSAGE,
            422,
            debug={"sql": generated.sql, "last_error": error.repair_hint or error.message},
        )

    def _call_provider(
        self, operation: Callable[[], LLMGeneration], deadline: Deadline
    ) -> LLMGeneration:
        started_at = perf_counter()
        error_code: str | None = None
        telemetry = get_request_telemetry()
        with span(
            "llm.call",
            provider=self.provider.name,
            request_id=telemetry.request_id if telemetry else None,
        ) as current:
            try:
                self._check_deadline(deadline)
                # Run in a copy of this context so the worker sees the same request telemetry.
                future = _provider_executor.submit(contextvars.copy_context().run, operation)
                try:
                    return future.result(timeout=deadline.remaining())
                except FutureTimeoutError:
                    if future.done():
                        raise  # the provider itself raised TimeoutError
                    future.cancel()
                    raise self._deadline_error() from None
            except LLMProviderError as error:
                error_code = error.code
                if self.provider.name == "gemini":
                    metrics.increment("gemini_failures_total")
                raise
            except AnalyticsServiceError as error:
                error_code = error.code
                raise
            except Exception:
                error_code = "UNEXPECTED_PROVIDER_ERROR"
                raise
            finally:
                elapsed = perf_counter() - started_at
                metrics.observe("llm_latency_ms", elapsed * 1000)
                metrics.record_llm_call(self.provider.name, elapsed, error_code)
                if error_code:
                    record_span_error(current, error_code)
                if telemetry:
                    telemetry.llm_latency_ms += elapsed * 1000

    def _resolve_context(
        self,
        conversation_id: str | None,
        conversation_context: str | None,
        owner: str | None,
    ) -> str | None:
        if conversation_context:
            return conversation_context
        if conversation_id is None:
            return None
        return self.conversation_memory.build_context(conversation_id, owner)

    def _to_generated_query(
        self,
        question: str,
        context: SchemaContext,
        generation: LLMGeneration,
    ) -> GeneratedQuery:
        known_tables = set(context.table_names)
        tables_used = [table for table in generation.tables_used if table in known_tables]
        return GeneratedQuery(
            question=question,
            sql=generation.sql,
            explanation=generation.explanation,
            tables_used=tables_used,
            schema_context=context.table_names,
            provider=self.provider.name,
            confidence=generation.confidence,
        )
