"""create analytics schema views

Creates the ``analytics`` schema that the ``analytics_readonly`` role reads instead of the
application tables. The views omit personal identifiers and filter rows to the caller's
tenant using transaction-local settings (``app.scope`` / ``app.customer_id``) set by the
query executor. Missing settings fail closed.

Row scoping lives in the views rather than in PostgreSQL RLS policies on the base tables:
the views are owned by the table owner, and an owner bypasses RLS, so a base-table policy
would not apply to queries that reach the data through the views. The role itself holds no
privileges on the base tables.

Revision ID: b7c2d41f8a10
Revises: 9a999e64b310
Create Date: 2026-10-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c2d41f8a10"
down_revision: str | Sequence[str] | None = "9a999e64b310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "analytics"
ROLE = "analytics_readonly"

# Frozen copy of the analytics surface at the time of this migration (see
# app/db/analytics_surface.py for the live definition used by application code).
TABLES = (
    "customers",
    "users",
    "vehicles",
    "drivers",
    "trips",
    "vehicle_locations",
    "fuel_records",
    "maintenance_records",
    "invoices",
    "payments",
    "subscriptions",
)
PII_COLUMNS = {
    "customers": {"name", "email"},
    "users": {"name", "email"},
    "drivers": {"name", "phone", "license_number"},
}
VIA_VEHICLE = {"vehicle_locations"}


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _row_filter(table: str) -> str:
    if table == "customers":
        return f"{SCHEMA}.row_visible(id)"
    if table in VIA_VEHICLE:
        return (
            "vehicle_id IN (SELECT v.id FROM public.vehicles v "
            f"WHERE {SCHEMA}.row_visible(v.customer_id))"
        )
    return f"{SCHEMA}.row_visible(customer_id)"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.row_visible(row_customer_id bigint)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        AS $$
            SELECT CASE current_setting('app.scope')
                WHEN 'global' THEN true
                WHEN 'tenant' THEN row_customer_id = NULLIF(current_setting('app.customer_id'), '')::bigint
                ELSE false
            END
        $$
        """
    )

    inspector = sa.inspect(bind)
    for table in TABLES:
        hidden = PII_COLUMNS.get(table, set())
        columns = [
            column["name"]
            for column in inspector.get_columns(table, schema="public")
            if column["name"] not in hidden
        ]
        column_list = ", ".join(_quote(name) for name in columns)
        op.execute(
            f"CREATE OR REPLACE VIEW {SCHEMA}.{_quote(table)} AS "
            f"SELECT {column_list} FROM public.{_quote(table)} WHERE {_row_filter(table)}"
        )

    # Privileges for the read-only role (it may not exist yet on a fresh database; the
    # database/init script grants the same privileges when it creates the role).
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{ROLE}') THEN
                EXECUTE 'GRANT USAGE ON SCHEMA {SCHEMA} TO {ROLE}';
                EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {ROLE}';
                EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE}';
                EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM {ROLE}';
                EXECUTE 'ALTER ROLE {ROLE} SET search_path = {SCHEMA}';
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{ROLE}') THEN
                EXECUTE 'ALTER ROLE {ROLE} RESET search_path';
                EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO {ROLE}';
                EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {ROLE}';
            END IF;
        END
        $$
        """
    )
    for table in reversed(TABLES):
        op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.{_quote(table)}")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.row_visible(bigint)")
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
