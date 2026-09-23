from app.services.schema_retriever import SchemaContext


class SQLPromptBuilder:
    def build(
        self,
        question: str,
        schema_context: SchemaContext,
        conversation_context: str | None = None,
    ) -> str:
        table_text = []
        for table in schema_context.tables:
            columns = ", ".join(f"{column.name} ({column.data_type})" for column in table.columns)
            relationships = (
                "; ".join(
                    f"{relationship.table}.{relationship.column} -> "
                    f"{relationship.references_table}.{relationship.references_column}"
                    for relationship in table.relationships
                )
                or "none"
            )
            table_text.append(
                f"- {table.name}: {table.description}\n"
                f"  columns: {columns}\n"
                f"  relationships: {relationships}"
            )

        definitions = (
            "\n".join(
                f"- {definition.name}: {definition.definition}"
                for definition in schema_context.business_definitions
            )
            or "- No specialized business definition applies."
        )
        conversation = conversation_context or "No prior conversation context."
        return f"""You generate read-only PostgreSQL analytics SQL.

Rules:
- Return one JSON object with these fields: sql, explanation, tables_used, confidence.
- Generate one SELECT statement only; never INSERT, UPDATE, DELETE, DDL, or multiple statements.
- Use only the supplied tables and columns. Do not invent identifiers.
- Use relationships and appropriate joins; avoid unnecessary columns.
- Use correct aggregation and a reasonable LIMIT for ranking questions.
- Do not include credentials, connection strings, or infrastructure details.
- The confidence value is informational and is not a security control.

SQL dialect: PostgreSQL
User question: {question}
Conversation context: {conversation}

Relevant schema:
{chr(10).join(table_text)}

Business definitions:
{definitions}
"""
