import logging
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.analytics.serialization import normalize_rows
from app.analytics.validator import SQLValidator, ValidationResult
from app.core.auth import Principal
from app.core.metrics import metrics
from app.core.telemetry import get_request_telemetry
from app.db.analytics_surface import SCOPE_DENY, SCOPE_GLOBAL, SCOPE_TENANT

logger = logging.getLogger(__name__)

_MAX_HINT_LENGTH = 300


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    execution_time_ms: float
    column_types: dict[str, str]
    truncated: bool = False


class AnalyticsServiceError(Exception):
    """A failure with a client-safe ``message`` and an internal ``repair_hint``.

    ``message`` is returned to API clients. ``repair_hint`` is richer (SQLSTATE and the database's
    primary message, or the validator's own errors) and is only ever given to the LLM repair
    step. ``debug`` is attached to error responses outside production only.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        repairable: bool = False,
        repair_hint: str | None = None,
        debug: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.repairable = repairable
        self.repair_hint = repair_hint
        self.debug = debug


# SQLSTATE -> (error code, HTTP status, repairable). See PostgreSQL Appendix A.
_SQLSTATE_ERRORS: dict[str, tuple[str, int, bool, str]] = {
    "57014": ("QUERY_TIMEOUT", 408, False, "The analytics query exceeded the configured timeout."),
    "55P03": ("QUERY_TIMEOUT", 408, False, "The analytics query exceeded the configured timeout."),
    "42501": (
        "QUERY_PERMISSION_ERROR",
        403,
        False,
        "The analytics database denied permission for this query.",
    ),
    "25006": (
        "QUERY_PERMISSION_ERROR",
        403,
        False,
        "The analytics database denied permission for this query.",
    ),
    "42P01": ("TABLE_NOT_FOUND", 404, True, "The requested table does not exist."),
    "42703": ("COLUMN_NOT_FOUND", 400, True, "The requested column does not exist."),
    "42883": ("FUNCTION_NOT_FOUND", 400, True, "The requested function is not available."),
}
_DATABASE_UNAVAILABLE_CLASSES = ("08", "53", "57P", "58")
_DATA_ERROR_CLASS = "22"


def _sqlstate(error: SQLAlchemyError) -> str | None:
    original = getattr(error, "orig", None)
    state = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return state if isinstance(state, str) and state else None


def _repair_hint(error: SQLAlchemyError, sqlstate: str | None) -> str:
    """A short, sanitized description of a database error for the repair prompt."""
    original = getattr(error, "orig", None)
    diagnostics = getattr(original, "diag", None)
    primary = getattr(diagnostics, "message_primary", None)
    if not primary:
        primary = str(original if original is not None else error)
    primary = re.sub(r"\s+", " ", str(primary).splitlines()[0] if str(primary) else "").strip()
    prefix = f"SQLSTATE {sqlstate}: " if sqlstate else ""
    return f"{prefix}{primary}"[:_MAX_HINT_LENGTH]


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

    def validate(self, sql: str, request_id: str | None = None) -> ValidationResult:
        started_at = perf_counter()
        result = self.validator.validate(sql)
        elapsed_ms = (perf_counter() - started_at) * 1000
        metrics.observe("sql_validation_latency_ms", elapsed_ms)
        telemetry = get_request_telemetry()
        if telemetry:
            telemetry.sql_validation_latency_ms += elapsed_ms
        if not result.valid:
            metrics.increment("validation_failures_total")
        logger.info(
            "analytics query validation completed",
            extra={
                "request_id": request_id,
                "validation_status": "valid" if result.valid else "invalid",
                "sql_validation_duration_ms": round(elapsed_ms, 2),
            },
        )
        return result

    def execute(
        self,
        sql: str,
        request_id: str | None = None,
        principal: Principal | None = None,
        timeout_seconds: float | None = None,
    ) -> QueryResult:
        validation = self.validate(sql, request_id=request_id)
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
                repair_hint="; ".join(validation.errors),
            )

        effective_timeout = self.query_timeout_seconds
        if timeout_seconds is not None:
            effective_timeout = min(effective_timeout, timeout_seconds)
        scope, customer_id = self._tenant_scope(principal)

        started_at = perf_counter()
        try:
            with self.engine.connect() as connection:
                is_postgresql = connection.dialect.name == "postgresql"
                if is_postgresql:
                    self._prepare_postgresql_transaction(
                        connection, effective_timeout, scope, customer_id
                    )
                result = connection.exec_driver_sql(
                    self._driver_sql(validation.normalized_sql or sql, connection)
                )
                rows = result.fetchmany(self.max_result_rows + 1)
                columns = list(result.keys())
        except SQLAlchemyError as error:
            raise self._translate_error(error, started_at, request_id) from error

        truncated = len(rows) > self.max_result_rows
        if truncated:
            rows = rows[: self.max_result_rows]

        elapsed_ms = (perf_counter() - started_at) * 1000
        metrics.observe("sql_execution_latency_ms", elapsed_ms)
        telemetry = get_request_telemetry()
        if telemetry:
            telemetry.sql_execution_latency_ms += elapsed_ms
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
            truncated=truncated,
        )

    @staticmethod
    def _tenant_scope(principal: Principal | None) -> tuple[str, str]:
        """Map the caller to the ``app.scope`` / ``app.customer_id`` database settings."""
        if principal is None:
            return SCOPE_DENY, ""
        if principal.is_global:
            return SCOPE_GLOBAL, ""
        if principal.customer_id is None:
            raise AnalyticsServiceError(
                "TENANT_REQUIRED",
                "The credentials are not associated with a customer.",
                403,
            )
        return SCOPE_TENANT, str(principal.customer_id)

    @staticmethod
    def _prepare_postgresql_transaction(
        connection: Connection, timeout_seconds: float, scope: str, customer_id: str
    ) -> None:
        """Configure the transaction before any query runs.

        ``set_config(..., true)`` is ``SET LOCAL``: every setting disappears at the end of the
        transaction, so nothing leaks onto the pooled connection. The tenant settings are read by
        the ``analytics.row_visible`` function that every analytics view applies.
        """
        timeout_ms = max(1, int(timeout_seconds * 1000))
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        connection.execute(
            text(
                "SELECT set_config('statement_timeout', :statement_timeout, true), "
                "set_config('lock_timeout', :lock_timeout, true), "
                "set_config('idle_in_transaction_session_timeout', :idle_timeout, true), "
                "set_config('app.scope', :scope, true), "
                "set_config('app.customer_id', :customer_id, true)"
            ),
            {
                "statement_timeout": str(timeout_ms),
                "lock_timeout": str(min(timeout_ms, 5000)),
                "idle_timeout": str(timeout_ms + 5000),
                "scope": scope,
                "customer_id": customer_id,
            },
        )

    @staticmethod
    def _driver_sql(sql: str, connection: Connection) -> str:
        """Prepare validated SQL for ``exec_driver_sql``.

        ``exec_driver_sql`` skips SQLAlchemy's ``:name`` bind-parameter parsing, so literals that
        contain colons are safe. psycopg's pyformat style treats ``%`` as a placeholder marker, so
        percent signs (``LIKE '%x%'``) must be doubled.
        """
        if connection.dialect.paramstyle in {"pyformat", "format"}:
            return sql.replace("%", "%%")
        return sql

    def _translate_error(
        self, error: SQLAlchemyError, started_at: float, request_id: str | None
    ) -> AnalyticsServiceError:
        elapsed_ms = (perf_counter() - started_at) * 1000
        metrics.observe("sql_execution_latency_ms", elapsed_ms)
        metrics.increment("sql_execution_failures_total")
        telemetry = get_request_telemetry()
        if telemetry:
            telemetry.sql_execution_latency_ms += elapsed_ms
        sqlstate = _sqlstate(error)
        logger.warning(
            "analytics query execution failed",
            extra={
                "request_id": request_id,
                "execution_time_ms": round(elapsed_ms, 2),
                "error_type": type(error).__name__,
            },
        )
        hint = _repair_hint(error, sqlstate)

        if isinstance(error, SQLAlchemyTimeoutError):
            return AnalyticsServiceError(
                "DATABASE_POOL_TIMEOUT",
                "The analytics database is busy. Please retry later.",
                503,
            )
        if sqlstate is not None:
            return self._from_sqlstate(sqlstate, hint)
        return self._from_message(error, hint)

    @staticmethod
    def _from_sqlstate(sqlstate: str, hint: str) -> AnalyticsServiceError:
        known = _SQLSTATE_ERRORS.get(sqlstate)
        if known is not None:
            code, status_code, repairable, message = known
            return AnalyticsServiceError(
                code,
                message,
                status_code,
                repairable=repairable,
                repair_hint=hint if repairable else None,
            )
        if sqlstate.startswith(_DATABASE_UNAVAILABLE_CLASSES):
            return AnalyticsServiceError(
                "DATABASE_UNAVAILABLE",
                "The analytics database is temporarily unavailable.",
                503,
            )
        if sqlstate.startswith(_DATA_ERROR_CLASS):
            return AnalyticsServiceError(
                "QUERY_DATA_ERROR",
                "The analytics query failed on the data it read.",
                400,
                repairable=True,
                repair_hint=hint,
            )
        return AnalyticsServiceError(
            "QUERY_EXECUTION_ERROR",
            "The analytics query could not be executed.",
            400,
            repairable=True,
            repair_hint=hint,
        )

    def _from_message(self, error: SQLAlchemyError, hint: str) -> AnalyticsServiceError:
        """Fallback for drivers that expose no SQLSTATE (SQLite, connection-level failures)."""
        message = str(error).lower()
        if "statement timeout" in message or "query_canceled" in message:
            return AnalyticsServiceError(
                "QUERY_TIMEOUT",
                "The analytics query exceeded the configured timeout.",
                408,
            )
        if "permission denied" in message or "must be owner" in message:
            return AnalyticsServiceError(
                "QUERY_PERMISSION_ERROR",
                "The analytics database denied permission for this query.",
                403,
            )
        if "no such table" in message or (
            "does not exist" in message and "relation" in message
        ):
            return AnalyticsServiceError(
                "TABLE_NOT_FOUND",
                "The requested table does not exist.",
                404,
                repairable=True,
                repair_hint=hint,
            )
        if isinstance(error, OperationalError) and (
            error.connection_invalidated or self.engine.dialect.name != "sqlite"
        ):
            return AnalyticsServiceError(
                "DATABASE_UNAVAILABLE",
                "The analytics database is temporarily unavailable.",
                503,
            )
        return AnalyticsServiceError(
            "QUERY_EXECUTION_ERROR",
            "The analytics query could not be executed.",
            400,
            repairable=True,
            repair_hint=hint,
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
