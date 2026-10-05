"""PostgreSQL integration tests for the analytics privilege and tenant-isolation model.

They run against a migrated and seeded database reached through ``ANALYTICS_DATABASE_URL`` (the
``analytics_readonly`` role) and skip when that is not PostgreSQL. They are the authoritative
check of the database half of the security boundary; the SQLite-based unit tests cannot cover it.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.analytics.service import AnalyticsQueryService
from app.core.auth import ANALYTICS_ADMIN_ROLE, Principal
from app.core.config import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine():
    settings = get_settings()
    if not settings.analytics_database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL analytics credentials are not configured")
    engine = create_engine(settings.analytics_database_url)
    yield engine
    engine.dispose()


def _scoped(connection, scope: str, customer_id: str = "") -> None:
    connection.execute(
        text(
            "SELECT set_config('app.scope', :scope, true), "
            "set_config('app.customer_id', :cid, true)"
        ),
        {"scope": scope, "cid": customer_id},
    )


def _visible_rows_without_scope(connection, table: str) -> int:
    """Row count seen with no scope set: an error (never set) or zero rows (reset to empty).

    A pooled connection that served an earlier request keeps an empty ``app.scope`` placeholder
    rather than losing the setting, so either outcome is the correct fail-closed behavior.
    """
    try:
        return connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
    except SQLAlchemyError:
        return 0


def test_role_can_read_views_but_cannot_modify_anything(engine) -> None:
    with engine.connect() as connection:
        _scoped(connection, "global")
        assert connection.execute(text("SELECT COUNT(*) FROM customers")).scalar_one() >= 0
        for statement in (
            "INSERT INTO analytics.customers (id) VALUES (999999)",
            "UPDATE analytics.customers SET company_name = 'probe' WHERE id = 1",
            "DELETE FROM analytics.customers WHERE id = 1",
            "DROP TABLE analytics.customers",
            "CREATE TABLE analytics.probe (id int)",
            "CREATE TABLE public.probe (id int)",
        ):
            with pytest.raises(SQLAlchemyError):
                connection.execute(text(statement))
            connection.rollback()
            _scoped(connection, "global")


@pytest.mark.parametrize(
    "table", ["customers", "vehicles", "alembic_version", "seed_runs", "users", "drivers"]
)
def test_role_cannot_read_base_tables_or_internal_tables(engine, table: str) -> None:
    with engine.connect() as connection:
        with pytest.raises(SQLAlchemyError):
            connection.execute(text(f"SELECT 1 FROM public.{table} LIMIT 1"))


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT email FROM customers",
        "SELECT name FROM customers",
        "SELECT email FROM users",
        "SELECT phone FROM drivers",
        "SELECT license_number FROM drivers",
    ],
)
def test_personal_data_columns_do_not_exist_in_the_views(engine, statement: str) -> None:
    with engine.connect() as connection:
        _scoped(connection, "global")
        with pytest.raises(SQLAlchemyError):
            connection.execute(text(statement))


def test_queries_fail_closed_when_no_scope_is_set(engine) -> None:
    with engine.connect() as connection:
        assert _visible_rows_without_scope(connection, "customers") == 0


def test_unrecognised_scope_sees_no_rows(engine) -> None:
    with engine.connect() as connection:
        _scoped(connection, "deny")
        assert connection.execute(text("SELECT COUNT(*) FROM vehicles")).scalar_one() == 0
        _scoped(connection, "tenant", "")
        assert connection.execute(text("SELECT COUNT(*) FROM vehicles")).scalar_one() == 0


def _two_customers(engine) -> tuple[int, int]:
    with engine.connect() as connection:
        _scoped(connection, "global")
        ids = [row[0] for row in connection.execute(text("SELECT id FROM customers ORDER BY id"))]
    if len(ids) < 2:
        pytest.skip("The database must be seeded with at least two customers")
    return ids[0], ids[1]


TENANT_TABLES_WITH_CUSTOMER_ID = [
    "users",
    "vehicles",
    "drivers",
    "trips",
    "fuel_records",
    "maintenance_records",
    "invoices",
    "payments",
    "subscriptions",
]


def test_global_scope_sees_every_tenant(engine) -> None:
    with engine.connect() as connection:
        _scoped(connection, "global")
        distinct = connection.execute(
            text("SELECT COUNT(DISTINCT customer_id) FROM vehicles")
        ).scalar_one()

    assert distinct >= 2


@pytest.mark.parametrize("table", TENANT_TABLES_WITH_CUSTOMER_ID)
def test_tenant_scope_only_sees_its_own_rows(engine, table: str) -> None:
    first, _ = _two_customers(engine)
    with engine.connect() as connection:
        _scoped(connection, "tenant", str(first))
        foreign = connection.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE customer_id <> :cid"), {"cid": first}
        ).scalar_one()

    assert foreign == 0


def test_tenant_scope_cannot_see_other_customers_rows(engine) -> None:
    first, second = _two_customers(engine)
    with engine.connect() as connection:
        _scoped(connection, "tenant", str(first))
        customers = connection.execute(text("SELECT id FROM customers")).scalars().all()

    assert customers == [first]
    assert second not in customers


def test_vehicle_locations_are_scoped_through_their_vehicle(engine) -> None:
    first, _ = _two_customers(engine)
    with engine.connect() as connection:
        _scoped(connection, "tenant", str(first))
        foreign = connection.execute(
            text(
                "SELECT COUNT(*) FROM vehicle_locations l "
                "JOIN vehicles v ON v.id = l.vehicle_id WHERE v.customer_id <> :cid"
            ),
            {"cid": first},
        ).scalar_one()
        visible_without_vehicle = connection.execute(
            text(
                "SELECT COUNT(*) FROM vehicle_locations "
                "WHERE vehicle_id NOT IN (SELECT id FROM vehicles)"
            )
        ).scalar_one()

    assert foreign == 0
    assert visible_without_vehicle == 0


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) FROM vehicles",
        "SELECT COUNT(*) FROM (SELECT customer_id FROM vehicles) s WHERE customer_id <> {cid}",
        "WITH v AS (SELECT * FROM vehicles) SELECT COUNT(*) FROM v WHERE customer_id <> {cid}",
        "SELECT COUNT(*) FROM vehicles v JOIN trips t ON t.vehicle_id = v.id "
        "WHERE v.customer_id <> {cid} OR t.customer_id <> {cid}",
        "SELECT COUNT(*) FROM vehicles WHERE id IN (SELECT vehicle_id FROM trips) "
        "AND customer_id <> {cid}",
        "SELECT COUNT(*) FROM invoices WHERE customer_id <> {cid} "
        "UNION ALL SELECT COUNT(*) FROM payments WHERE customer_id <> {cid}",
    ],
)
def test_tenant_isolation_holds_for_joins_subqueries_ctes_and_unions(engine, sql: str) -> None:
    first, _ = _two_customers(engine)
    service = AnalyticsQueryService(engine)
    principal = Principal("tenant-user", customer_id=first, roles=("analyst",))

    result = service.execute(sql.format(cid=first), principal=principal)

    if "<>" in sql:
        assert all(value == 0 for row in result.rows for value in row.values())
    else:
        global_total = service.execute(
            sql, principal=Principal("admin", roles=(ANALYTICS_ADMIN_ROLE,))
        ).rows[0]["count"]
        assert result.rows[0]["count"] < global_total


def test_executor_applies_scope_per_request_and_leaves_nothing_on_the_connection(engine) -> None:
    first, _ = _two_customers(engine)
    service = AnalyticsQueryService(engine)

    tenant = service.execute(
        "SELECT COUNT(*) AS n FROM customers",
        principal=Principal("t", customer_id=first, roles=("analyst",)),
    )
    admin = service.execute(
        "SELECT COUNT(*) AS n FROM customers",
        principal=Principal("a", roles=(ANALYTICS_ADMIN_ROLE,)),
    )
    denied = service.execute("SELECT COUNT(*) AS n FROM customers", principal=None)

    assert tenant.rows == [{"n": 1}]
    assert admin.rows[0]["n"] >= 2
    assert denied.rows == [{"n": 0}]
    with engine.connect() as connection:
        # Session state set for earlier requests must not leak onto pooled connections.
        assert connection.execute(text("SHOW statement_timeout")).scalar_one() in {"0", "0ms"}
        assert _visible_rows_without_scope(connection, "customers") == 0


def test_executor_opens_a_read_only_transaction_before_any_query(engine) -> None:
    from sqlalchemy import event

    statements: list[str] = []

    def record(connection, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        AnalyticsQueryService(engine).execute(
            "SELECT COUNT(*) AS n FROM vehicles",
            principal=Principal("a", roles=(ANALYTICS_ADMIN_ROLE,)),
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)

    executed = [statement for statement in statements if statement.strip() != "SELECT 1"]
    assert executed[0] == "SET TRANSACTION READ ONLY"
    assert "set_config" in executed[1]
    assert "SELECT COUNT(*)" in executed[2].upper()
