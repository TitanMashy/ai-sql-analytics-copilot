from dataclasses import dataclass

from sqlalchemy import inspect

from app.db.base import Base
from app.models import entities  # noqa: F401


@dataclass(frozen=True)
class ColumnMetadata:
    name: str
    data_type: str
    nullable: bool


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


def get_schema_metadata() -> tuple[TableMetadata, ...]:
    metadata = []
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name):
        if table.name == "seed_runs":
            continue
        columns = tuple(
            ColumnMetadata(column.name, str(column.type), column.nullable)
            for column in table.columns
        )
        relationships = tuple(
            RelationshipMetadata(
                table.name,
                column.name,
                foreign_key.column.table.name,
                foreign_key.column.name,
            )
            for column in table.columns
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


def get_database_schema(engine: object) -> tuple[TableMetadata, ...]:
    """Return metadata for tables currently present in a database connection."""
    inspector = inspect(engine)
    present_tables = set(inspector.get_table_names())
    return tuple(table for table in get_schema_metadata() if table.name in present_tables)
