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
    """Selects the schema shown to the model.

    The analytics surface is small (11 tables), so by default every table is included and
    keyword scoring only decides the *order*, putting the most relevant tables first. A wrong
    retrieval can therefore no longer hide a table the question needs. ``full_schema=False``
    restores narrowed retrieval (top five tables plus one hop of foreign-key parents) for much
    larger schemas; in that mode the previous conversation turns also contribute to scoring, and
    a question with no keyword match falls back to the whole schema rather than an arbitrary
    three tables.
    """

    def __init__(
        self,
        metadata: tuple[TableMetadata, ...] | None = None,
        full_schema: bool = True,
    ) -> None:
        self.metadata = metadata or get_schema_metadata()
        self.full_schema = full_schema

    def retrieve(self, question: str, conversation_context: str | None = None) -> SchemaContext:
        scored = self._score(question)
        if not scored and conversation_context:
            scored = self._score(f"{question} {conversation_context}")
        scored.sort(key=lambda item: (-item[0], item[1].name))
        ranked = [table for _, table in scored]

        if self.full_schema or not ranked:
            ranked_names = {table.name for table in ranked}
            selected = ranked + [table for table in self.metadata if table.name not in ranked_names]
        else:
            selected = ranked[:5]
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

        definition_text = question
        if conversation_context:
            definition_text = f"{question} {conversation_context}"
        return SchemaContext(
            tables=tuple(selected),
            business_definitions=relevant_business_definitions(definition_text),
        )

    def _score(self, text: str) -> list[tuple[int, TableMetadata]]:
        normalized = text.casefold()
        scored: list[tuple[int, TableMetadata]] = []
        for table in self.metadata:
            keyword_score = sum(
                2 if keyword in normalized else 0 for keyword in TABLE_KEYWORDS.get(table.name, ())
            )
            column_score = sum(
                1 for column in table.columns if column.name.casefold() in normalized
            )
            score = keyword_score + column_score
            if score:
                scored.append((score, table))
        return scored
