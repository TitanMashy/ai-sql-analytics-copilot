import logging
from dataclasses import dataclass, replace

from app.analytics.service import AnalyticsQueryService, AnalyticsServiceError, QueryResult
from app.llm.prompt import SQLPromptBuilder
from app.llm.provider import LLMGeneration, LLMProvider, LLMProviderError
from app.services.result_analyzer import AnalyticsResultAnalyzer
from app.services.result_models import ResultAnalysis
from app.services.result_summary import ResultSummaryService
from app.services.schema_retriever import SchemaContext, SchemaRetriever
from app.services.visualization import VisualizationSelector

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.provider = provider
        self.retriever = retriever or SchemaRetriever()
        self.prompt_builder = prompt_builder or SQLPromptBuilder()
        self.analytics_service = analytics_service
        self.max_repair_retries = max_repair_retries
        self.result_analyzer = result_analyzer or AnalyticsResultAnalyzer()
        self.visualization_selector = visualization_selector or VisualizationSelector()
        self.summary_service = summary_service or ResultSummaryService()

    def generate(
        self,
        question: str,
        conversation_context: str | None = None,
    ) -> GeneratedQuery:
        if not question.strip():
            raise LLMProviderError("INVALID_REQUEST", "Question cannot be empty.", 422)
        context = self.retriever.retrieve(question)
        generation = self.provider.generate_sql(question, context, conversation_context)
        return self._to_generated_query(question, context, generation)

    def ask(
        self,
        question: str,
        request_id: str | None = None,
        conversation_context: str | None = None,
    ) -> AskedQuery:
        if self.analytics_service is None:
            raise RuntimeError("AnalyticsQueryService is required for ask")
        context = self.retriever.retrieve(question)
        generated = self.generate(question, conversation_context)
        repair_attempts = 0
        while True:
            try:
                result = self.analytics_service.execute(generated.sql, request_id=request_id)
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
                analysis = replace(analysis, visualization=visualization)
                summary = self.summary_service.summarize(
                    question, generated.sql, result.columns, result.rows, analysis
                )
                return AskedQuery(
                    generated=generated,
                    result=result,
                    analysis=analysis,
                    summary=summary,
                )
            except AnalyticsServiceError as error:
                if not error.repairable or repair_attempts >= self.max_repair_retries:
                    raise
                repair_attempts += 1
                logger.info(
                    "repairing analytics SQL",
                    extra={"repair_attempt": repair_attempts},
                )
                repaired = self.provider.repair_sql(
                    question,
                    generated.sql,
                    error.message,
                    context,
                )
                generated = self._to_generated_query(question, context, repaired)

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
