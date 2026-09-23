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
    column_types: dict[str, str]


class AnalyticsServiceError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        repairable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.repairable = repairable


class AnalyticsQueryService:
    def __init__(
        self,
        engine: Engine,
        validator: SQLValidator | None = None,
        max_result_rows: int = 1000,
        query_timeout_seconds: float = 10.0,
        max_query_joins: int = 5,
        max_query_nesting: int = 3,
    ) -> None:
        self.engine = engine
        self.validator = validator or SQLValidator(
            max_result_rows=max_result_rows,
            max_query_joins=max_query_joins,
            max_query_nesting=max_query_nesting,
        )
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
            error_code = validation.error_code
            status_code = 400
            if validation.error_code == "QUERY_VALIDATION_ERROR" and any(
                error.startswith("Unknown or disallowed table") for error in validation.errors
            ):
                error_code = "TABLE_NOT_FOUND"
                status_code = 404
                error_message = "The requested table does not exist."
            else:
                error_message = "; ".join(validation.errors)
            raise AnalyticsServiceError(
                error_code,
                error_message,
                status_code,
                repairable=validation.repairable,
            )

        started_at = perf_counter()
        try:
            with self.engine.connect() as connection:
                if connection.dialect.name == "postgresql":
                    timeout_ms = max(1, int(self.query_timeout_seconds * 1000))
                    connection.execute(text(f"SET statement_timeout = {timeout_ms}"))
                result = connection.execute(text(validation.normalized_sql or sql))
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
            if "permission denied" in message or "must be owner" in message:
                raise AnalyticsServiceError(
                    "QUERY_PERMISSION_ERROR",
                    "The analytics database denied permission for this query.",
                    403,
                ) from error
            if "does not exist" in message or "no such table" in message:
                raise AnalyticsServiceError(
                    "TABLE_NOT_FOUND",
                    "The requested table does not exist.",
                    404,
                    repairable=True,
                ) from error
            raise AnalyticsServiceError(
                "QUERY_EXECUTION_ERROR",
                "The analytics query could not be executed.",
                400,
                repairable=True,
            ) from error

        if len(rows) > self.max_result_rows:
            raise AnalyticsServiceError(
                "RESULT_LIMIT_EXCEEDED",
                f"The query returned more than {self.max_result_rows} rows.",
                400,
            )

        elapsed_ms = (perf_counter() - started_at) * 1000
        normalized_rows = normalize_rows([row._mapping for row in rows])
        column_types = {
            column: self._infer_column_type([row.get(column) for row in normalized_rows])
            for column in columns
        }
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
            column_types=column_types,
        )

    @staticmethod
    def _infer_column_type(values: list[Any]) -> str:
        for value in values:
            if value is None:
                continue
            if isinstance(value, bool):
                return "boolean"
            if isinstance(value, int):
                return "integer"
            if isinstance(value, float):
                return "numeric"
            if isinstance(value, str):
                return "string"
        return "unknown"
