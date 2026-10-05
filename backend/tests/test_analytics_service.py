from time import perf_counter
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.pool import StaticPool

from app.analytics.service import AnalyticsQueryService, AnalyticsServiceError
from app.core.auth import ANALYTICS_ADMIN_ROLE, Principal


class FakeDriverError(Exception):
    """Stands in for a psycopg error: carries a SQLSTATE and server diagnostics."""

    def __init__(self, sqlstate: str, primary: str) -> None:
        super().__init__(primary)
        self.sqlstate = sqlstate
        self.diag = SimpleNamespace(message_primary=primary)


def _service() -> AnalyticsQueryService:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE vehicles (id INTEGER, status TEXT)"))
        connection.execute(text("INSERT INTO vehicles VALUES (1, 'active'), (2, 'inactive')"))
    return AnalyticsQueryService(engine, max_result_rows=1)


def _translate(sqlstate: str, primary: str) -> AnalyticsServiceError:
    error = OperationalError("SELECT 1", {}, FakeDriverError(sqlstate, primary))
    return _service()._translate_error(error, perf_counter(), "request-1")


@pytest.mark.parametrize(
    ("sqlstate", "code", "status", "repairable"),
    [
        ("42P01", "TABLE_NOT_FOUND", 404, True),
        ("42703", "COLUMN_NOT_FOUND", 400, True),
        ("42883", "FUNCTION_NOT_FOUND", 400, True),
        ("57014", "QUERY_TIMEOUT", 408, False),
        ("55P03", "QUERY_TIMEOUT", 408, False),
        ("42501", "QUERY_PERMISSION_ERROR", 403, False),
        ("25006", "QUERY_PERMISSION_ERROR", 403, False),
        ("22012", "QUERY_DATA_ERROR", 400, True),
        ("22P02", "QUERY_DATA_ERROR", 400, True),
        ("08006", "DATABASE_UNAVAILABLE", 503, False),
        ("53300", "DATABASE_UNAVAILABLE", 503, False),
        ("57P01", "DATABASE_UNAVAILABLE", 503, False),
        ("42601", "QUERY_EXECUTION_ERROR", 400, True),
        ("XX000", "QUERY_EXECUTION_ERROR", 400, True),
    ],
)
def test_database_errors_are_classified_by_sqlstate(
    sqlstate: str, code: str, status: int, repairable: bool
) -> None:
    error = _translate(sqlstate, 'column "x" does not exist')

    assert error.code == code
    assert error.status_code == status
    assert error.repairable is repairable


def test_missing_column_is_not_reported_as_a_missing_table() -> None:
    # PostgreSQL's message for an unknown column also says "does not exist".
    error = _translate("42703", 'column "fuel_cost" does not exist')

    assert error.code == "COLUMN_NOT_FOUND"
    assert error.code != "TABLE_NOT_FOUND"


def test_repair_hint_carries_sqlstate_and_the_database_message() -> None:
    error = _translate("42703", 'column "fuel_cost" does not exist')

    assert error.repair_hint == 'SQLSTATE 42703: column "fuel_cost" does not exist'


def test_public_message_never_contains_the_database_detail() -> None:
    error = _translate("42703", 'column "fuel_cost" does not exist')

    assert "fuel_cost" not in error.message
    assert "SQLSTATE" not in error.message


def test_repair_hint_is_single_line_and_bounded() -> None:
    error = _translate("22P02", "invalid input syntax\n" + "x" * 1000)

    assert "\n" not in error.repair_hint
    assert len(error.repair_hint) <= 300


def test_non_repairable_failures_carry_no_hint() -> None:
    assert _translate("57014", "canceling statement").repair_hint is None
    assert _translate("42501", "permission denied for table x").repair_hint is None


def test_pool_exhaustion_maps_to_a_busy_error() -> None:
    error = _service()._translate_error(
        SQLAlchemyTimeoutError("QueuePool limit reached"), perf_counter(), None
    )

    assert error.code == "DATABASE_POOL_TIMEOUT"
    assert error.status_code == 503


# -- transaction preparation and tenant scope -----------------------------------------------


class RecordingConnection:
    def __init__(self) -> None:
        self.driver_sql: list[str] = []
        self.statements: list[tuple[str, dict]] = []

    def exec_driver_sql(self, sql: str) -> None:
        self.driver_sql.append(sql)

    def execute(self, statement, parameters: dict) -> None:
        self.statements.append((str(statement), parameters))


def test_postgresql_transaction_is_read_only_with_local_settings() -> None:
    connection = RecordingConnection()

    AnalyticsQueryService._prepare_postgresql_transaction(connection, 10.0, "tenant", "42")

    assert connection.driver_sql == ["SET TRANSACTION READ ONLY"]
    statement, parameters = connection.statements[0]
    # ``true`` as the third argument makes every setting transaction-local (SET LOCAL), so
    # nothing survives on the pooled connection.
    assert statement.count(", true)") == 5
    assert parameters == {
        "statement_timeout": "10000",
        "lock_timeout": "5000",
        "idle_timeout": "15000",
        "scope": "tenant",
        "customer_id": "42",
    }


def test_short_remaining_budget_shortens_every_timeout() -> None:
    connection = RecordingConnection()

    AnalyticsQueryService._prepare_postgresql_transaction(connection, 0.5, "global", "")

    parameters = connection.statements[0][1]
    assert parameters["statement_timeout"] == "500"
    assert parameters["lock_timeout"] == "500"
    assert parameters["scope"] == "global"


def test_tenant_scope_mapping() -> None:
    scope = AnalyticsQueryService._tenant_scope

    assert scope(Principal("a", customer_id=5, roles=("analyst",))) == ("tenant", "5")
    assert scope(Principal("a", roles=(ANALYTICS_ADMIN_ROLE,))) == ("global", "")
    assert scope(None) == ("deny", "")


def test_non_admin_principal_without_a_customer_is_refused() -> None:
    service = _service()

    with pytest.raises(AnalyticsServiceError) as error:
        service.execute("SELECT id FROM vehicles", principal=Principal("a"))

    assert error.value.code == "TENANT_REQUIRED"
    assert error.value.status_code == 403


# -- driver SQL preparation -----------------------------------------------------------------


def test_percent_signs_are_doubled_only_for_pyformat_drivers() -> None:
    sql = "SELECT 1 FROM vehicles WHERE status LIKE 'a%'"
    pyformat = SimpleNamespace(dialect=SimpleNamespace(paramstyle="pyformat"))
    qmark = SimpleNamespace(dialect=SimpleNamespace(paramstyle="qmark"))

    assert AnalyticsQueryService._driver_sql(sql, pyformat) == (
        "SELECT 1 FROM vehicles WHERE status LIKE 'a%%'"
    )
    assert AnalyticsQueryService._driver_sql(sql, qmark) == sql


def test_execution_truncates_and_flags_results_over_the_cap() -> None:
    result = _service().execute("SELECT id FROM vehicles ORDER BY id")

    assert result.truncated is True
    assert result.row_count == 1
    assert result.rows == [{"id": 1}]


def test_execution_does_not_flag_results_within_the_cap() -> None:
    result = _service().execute("SELECT id FROM vehicles WHERE id = 1")

    assert result.truncated is False
