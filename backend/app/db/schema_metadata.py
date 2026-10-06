import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import CheckConstraint, inspect

from app.db.analytics_surface import PII_COLUMNS
from app.db.base import Base
from app.models import entities  # noqa: F401


@dataclass(frozen=True)
class ColumnMetadata:
    name: str
    data_type: str
    nullable: bool
    allowed_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelationshipMetadata:
    table: str
    column: str
    references_table: str
    references_column: str


@dataclass(frozen=True)
class TableMetadata:
    name: str
    description: str
    columns: tuple[ColumnMetadata, ...]
    relationships: tuple[RelationshipMetadata, ...]


TABLE_DESCRIPTIONS = {
    "customers": "Fleet-management SaaS tenants and their regional profile.",
    "users": "Customer users who operate the fleet-management platform.",
    "vehicles": "Vehicles managed by each customer fleet.",
    "drivers": "Drivers assigned to customer fleets.",
    "trips": "Historical and active vehicle journeys with utilization measures.",
    "vehicle_locations": "Time-series GPS and speed observations for vehicles.",
    "fuel_records": "Fuel purchases and spend by vehicle and customer.",
    "maintenance_records": "Vehicle service events and maintenance costs.",
    "invoices": "Customer billing invoices and collection state.",
    "payments": "Payments applied to customer invoices.",
    "subscriptions": "Customer subscription plans and recurring prices.",
}


_IN_CHECK = re.compile(r"(\w+)\s+IN\s*\(([^)]*)\)", re.IGNORECASE)
_QUOTED_VALUE = re.compile(r"'([^']*)'")


def _allowed_values(table) -> dict[str, tuple[str, ...]]:
    """Enumerated values from ``column IN ('a', 'b')`` CHECK constraints."""
    values: dict[str, tuple[str, ...]] = {}
    for constraint in table.constraints:
        if not isinstance(constraint, CheckConstraint):
            continue
        for column_name, options in _IN_CHECK.findall(str(constraint.sqltext)):
            parsed = tuple(_QUOTED_VALUE.findall(options))
            if parsed:
                values[column_name] = parsed
    return values


def get_schema_metadata() -> tuple[TableMetadata, ...]:
    """Metadata for the analytics surface: allowed tables, minus personal-data columns."""
    metadata = []
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name):
        if table.name == "seed_runs":
            continue
        hidden = PII_COLUMNS.get(table.name, frozenset())
        enumerations = _allowed_values(table)
        columns = tuple(
            ColumnMetadata(
                column.name,
                str(column.type),
                column.nullable,
                enumerations.get(column.name, ()),
            )
            for column in table.columns
            if column.name not in hidden
        )
        relationships = tuple(
            RelationshipMetadata(
                table.name,
                column.name,
                foreign_key.column.table.name,
                foreign_key.column.name,
            )
            for column in table.columns
            if column.name not in hidden
            for foreign_key in column.foreign_keys
        )
        metadata.append(
            TableMetadata(
                name=table.name,
                description=TABLE_DESCRIPTIONS.get(table.name, "Fleet analytics data."),
                columns=columns,
                relationships=relationships,
            )
        )
    return tuple(metadata)


@lru_cache
def schema_fingerprint() -> str:
    """A short hash of the analytics surface (tables, columns, types, enum values).

    Used to version caches: any schema change produces a new fingerprint, which invalidates
    entries created against the old schema.
    """
    digest = hashlib.sha256()
    for table in get_schema_metadata():
        digest.update(table.name.encode())
        for column in table.columns:
            allowed = ",".join(column.allowed_values)
            digest.update(f"|{column.name}:{column.data_type}:{allowed}".encode())
        digest.update(b";")
    return digest.hexdigest()[:16]


def get_database_schema(engine: object) -> tuple[TableMetadata, ...]:
    """Return metadata for tables currently present in a database connection."""
    inspector = inspect(engine)
    present_tables = set(inspector.get_table_names())
    return tuple(table for table in get_schema_metadata() if table.name in present_tables)
