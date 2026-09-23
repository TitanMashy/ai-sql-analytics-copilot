from dataclasses import dataclass


@dataclass(frozen=True)
class BusinessDefinition:
    name: str
    definition: str
    keywords: tuple[str, ...]


BUSINESS_DEFINITIONS = (
    BusinessDefinition(
        "revenue",
        (
            "Use SUM(invoices.total_amount) for non-cancelled invoices. Payments represent "
            "cash collection, not billed revenue."
        ),
        ("revenue", "sales", "income", "billing"),
    ),
    BusinessDefinition(
        "active vehicle",
        "An active vehicle is a row in vehicles where vehicles.status = 'active'.",
        ("active vehicle", "active vehicles", "fleet"),
    ),
    BusinessDefinition(
        "completed trip",
        "A completed trip is a row in trips where trips.trip_status = 'completed'.",
        ("trip", "trips", "distance", "utilization", "idle"),
    ),
    BusinessDefinition(
        "fuel cost",
        "Fuel cost is SUM(fuel_records.total_cost).",
        ("fuel", "fuel cost", "consumption"),
    ),
    BusinessDefinition(
        "idle time",
        "Idle time is SUM(trips.idle_time_minutes), or AVG for an average-idle question.",
        ("idle", "idling"),
    ),
    BusinessDefinition(
        "payments",
        (
            "Payments are linked to invoices by payments.invoice_id and use payments.status "
            "for collection state."
        ),
        ("payment", "payments", "collection", "collected", "paid"),
    ),
)


def relevant_business_definitions(question: str) -> tuple[BusinessDefinition, ...]:
    normalized = question.casefold()
    return tuple(
        definition
        for definition in BUSINESS_DEFINITIONS
        if any(keyword in normalized for keyword in definition.keywords)
    )
