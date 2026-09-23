import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.analytics.serialization import normalize_rows
from app.analytics.validator import SQLValidator, ValidationResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    execution_time_ms: float


class AnalyticsServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class AnalyticsQueryService:
    def __init__(
        self,
        engine: Engine,
        validator: SQLValidator | None = None,
        max_result_rows: int = 1000,
        query_timeout_seconds: float = 10.0,
    ) -> None:
        self.engine = engine
        self.validator = validator or SQLValidator()
        self.max_result_rows = max_result_rows
        self.query_timeout_seconds = query_timeout_seconds

    def validate(self, sql: str) -> ValidationResult:
        result = self.validator.validate(sql)
        logger.info(
            "analytics query validation completed",
            extra={"validation_status": "valid" if result.valid else "invalid"},
        )
        return result

    def execute(self, sql: str, request_id: str | None = None) -> QueryResult:
        validation = self.validate(sql)
        if not validation.valid:
            raise AnalyticsServiceError(
                "QUERY_VALIDATION_ERROR",
                "; ".join(validation.errors),
                400,
            )

        started_at = perf_counter()
        try:
            with self.engine.connect() as connection:
                if connection.dialect.name == "postgresql":
                    timeout_ms = max(1, int(self.query_timeout_seconds * 1000))
                    connection.execute(text(f"SET statement_timeout = {timeout_ms}"))
                result = connection.execute(text(sql))
                rows = result.fetchmany(self.max_result_rows + 1)
                columns = list(result.keys())
        except SQLAlchemyError as error:
            elapsed_ms = (perf_counter() - started_at) * 1000
            logger.exception(
                "analytics query execution failed",
                extra={"request_id": request_id, "execution_time_ms": round(elapsed_ms, 2)},
            )
            message = str(error).lower()
            if "statement timeout" in message or "query_canceled" in message:
                raise AnalyticsServiceError(
                    "QUERY_TIMEOUT",
                    "The analytics query exceeded the configured timeout.",
                    408,
                ) from error
            if "does not exist" in message or "no such table" in message:
                raise AnalyticsServiceError(
                    "TABLE_NOT_FOUND",
                    "The requested table does not exist.",
                    404,
                ) from error
            raise AnalyticsServiceError(
                "QUERY_EXECUTION_ERROR",
                "The analytics query could not be executed.",
                400,
            ) from error

        if len(rows) > self.max_result_rows:
            raise AnalyticsServiceError(
                "RESULT_LIMIT_EXCEEDED",
                f"The query returned more than {self.max_result_rows} rows.",
                400,
            )

        elapsed_ms = (perf_counter() - started_at) * 1000
        normalized_rows = normalize_rows([row._mapping for row in rows])
        logger.info(
            "analytics query executed",
            extra={
                "request_id": request_id,
                "execution_time_ms": round(elapsed_ms, 2),
                "result_row_count": len(normalized_rows),
            },
        )
        return QueryResult(
            columns=columns,
            rows=normalized_rows,
            row_count=len(normalized_rows),
            execution_time_ms=round(elapsed_ms, 2),
        )
