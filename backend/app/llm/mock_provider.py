from app.llm.provider import LLMGeneration, LLMProviderError
from app.services.schema_retriever import SchemaContext


class MockLLMProvider:
    name = "mock"

    def generate_sql(
        self,
        question: str,
        schema_context: SchemaContext,
        conversation_context: str | None = None,
    ) -> LLMGeneration:
        del schema_context, conversation_context
        normalized = " ".join(question.casefold().split())
        if "active" in normalized and "vehicle" in normalized:
            return LLMGeneration(
                sql="SELECT COUNT(*) AS active_vehicle_count FROM vehicles WHERE status = 'active'",
                explanation="Counts vehicles whose status is active.",
                tables_used=["vehicles"],
                confidence=0.99,
            )
        if "top" in normalized and "customer" in normalized and "revenue" in normalized:
            return LLMGeneration(
                sql=(
                    "SELECT c.company_name, SUM(i.total_amount) AS total_revenue "
                    "FROM customers c JOIN invoices i ON i.customer_id = c.id "
                    "WHERE i.status <> 'cancelled' "
                    "GROUP BY c.id, c.company_name ORDER BY total_revenue DESC LIMIT 10"
                ),
                explanation="Ranks customers by non-cancelled invoice revenue.",
                tables_used=["customers", "invoices"],
                confidence=0.96,
            )
        if "monthly" in normalized and "revenue" in normalized:
            return LLMGeneration(
                sql=(
                    "SELECT DATE_TRUNC('month', invoice_date) AS revenue_month, "
                    "SUM(total_amount) AS total_revenue FROM invoices "
                    "WHERE status <> 'cancelled' AND invoice_date >= "
                    "(SELECT MAX(invoice_date) - INTERVAL '12 months' FROM invoices) "
                    "GROUP BY revenue_month ORDER BY revenue_month"
                ),
                explanation=(
                    "Aggregates non-cancelled invoice revenue by month for the latest "
                    "twelve months in the dataset."
                ),
                tables_used=["invoices"],
                confidence=0.94,
            )
        if "idle" in normalized and "vehicle" in normalized:
            return LLMGeneration(
                sql=(
                    "SELECT v.registration_number, "
                    "AVG(t.idle_time_minutes) AS average_idle_minutes "
                    "FROM vehicles v JOIN trips t ON t.vehicle_id = v.id "
                    "GROUP BY v.id, v.registration_number "
                    "ORDER BY average_idle_minutes DESC LIMIT 10"
                ),
                explanation="Ranks vehicles by average trip idle time.",
                tables_used=["vehicles", "trips"],
                confidence=0.95,
            )
        if "fuel" in normalized and ("vehicle" in normalized or "consumption" in normalized):
            return LLMGeneration(
                sql=(
                    "SELECT v.registration_number, SUM(f.liters) AS total_liters, "
                    "SUM(f.total_cost) AS total_fuel_cost FROM vehicles v "
                    "JOIN fuel_records f ON f.vehicle_id = v.id "
                    "GROUP BY v.id, v.registration_number ORDER BY total_liters DESC LIMIT 10"
                ),
                explanation="Summarizes fuel volume and cost by vehicle.",
                tables_used=["vehicles", "fuel_records"],
                confidence=0.94,
            )
        raise LLMProviderError(
            "MOCK_QUERY_UNSUPPORTED",
            "Mock mode does not have a deterministic response for this question.",
            422,
        )

    def repair_sql(
        self,
        question: str,
        original_sql: str,
        error_message: str,
        schema_context: SchemaContext,
    ) -> LLMGeneration:
        del original_sql, error_message
        return self.generate_sql(question, schema_context)
