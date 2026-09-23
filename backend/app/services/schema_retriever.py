from dataclasses import dataclass

from app.db.schema_metadata import TableMetadata, get_schema_metadata
from app.services.business_definitions import (
    BusinessDefinition,
    relevant_business_definitions,
)


@dataclass(frozen=True)
class SchemaContext:
    tables: tuple[TableMetadata, ...]
    business_definitions: tuple[BusinessDefinition, ...]

    @property
    def table_names(self) -> list[str]:
        return [table.name for table in self.tables]


TABLE_KEYWORDS = {
    "customers": ("customer", "customers", "company", "client", "regional", "region"),
    "users": ("user", "users", "operator"),
    "vehicles": ("vehicle", "vehicles", "fleet", "active"),
    "drivers": ("driver", "drivers", "license"),
    "trips": ("trip", "trips", "distance", "utilization", "idle", "journey"),
    "vehicle_locations": ("location", "gps", "speed", "position"),
    "fuel_records": ("fuel", "consumption", "liters"),
    "maintenance_records": ("maintenance", "repair", "service"),
    "invoices": ("revenue", "invoice", "invoices", "sales", "billing", "customer"),
    "payments": ("revenue", "payment", "payments", "collection", "paid"),
    "subscriptions": ("subscription", "plan", "monthly", "recurring"),
}


class SchemaRetriever:
    def __init__(self, metadata: tuple[TableMetadata, ...] | None = None) -> None:
        self.metadata = metadata or get_schema_metadata()

    def retrieve(self, question: str) -> SchemaContext:
        normalized = question.casefold()
        scored_tables: list[tuple[int, TableMetadata]] = []
        for table in self.metadata:
            keyword_score = sum(
                2 if keyword in normalized else 0 for keyword in TABLE_KEYWORDS.get(table.name, ())
            )
            column_score = sum(
                1 for column in table.columns if column.name.casefold() in normalized
            )
            score = keyword_score + column_score
            if score:
                scored_tables.append((score, table))

        scored_tables.sort(key=lambda item: (-item[0], item[1].name))
        selected = [table for _, table in scored_tables[:5]]
        if not selected:
            selected = list(self.metadata[:3])

        selected_names = {table.name for table in selected}
        referenced_names = {
            relationship.references_table
            for table in selected
            for relationship in table.relationships
        }
        for table in self.metadata:
            if table.name in selected_names or table.name not in referenced_names:
                continue
            selected.append(table)

        return SchemaContext(
            tables=tuple(selected),
            business_definitions=relevant_business_definitions(question),
        )
