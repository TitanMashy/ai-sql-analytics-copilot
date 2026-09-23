from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from app.analytics.serialization import normalize_value
from app.services.result_analyzer import AnalyticsResultAnalyzer
from app.services.result_models import Visualization, VisualizationAxis
from app.services.result_summary import ResultSummaryService
from app.services.visualization import VisualizationSelector

analyzer = AnalyticsResultAnalyzer()
selector = VisualizationSelector()


def analyze(question: str, columns: list[str], rows: list[dict], types: dict[str, str]):
    return analyzer.analyze(question, "SELECT ...", columns, rows, 4.2, len(rows), types)


def test_kpi_detection_for_revenue_vehicle_count_and_average_distance() -> None:
    revenue = analyze(
        "What is total revenue?",
        ["total_revenue"],
        [{"total_revenue": Decimal("1254300.00")}],
        {"total_revenue": "numeric"},
    )
    vehicles = analyze(
        "What is the number of active vehicles?",
        ["active_vehicle_count"],
        [{"active_vehicle_count": 766}],
        {"active_vehicle_count": "integer"},
    )
    distance = analyze(
        "What is average trip distance?",
        ["average_distance_km"],
        [{"average_distance_km": 42.5}],
        {"average_distance_km": "numeric"},
    )

    assert revenue.kpi and revenue.kpi.format == "currency"
    assert vehicles.kpi and vehicles.kpi.format == "integer"
    assert distance.kpi and distance.kpi.format == "decimal"


def test_visualization_rules() -> None:
    time_series = analyze(
        "monthly revenue",
        ["month", "revenue"],
        [{"month": "2025-01-01T00:00:00+00:00", "revenue": 10.0}],
        {"month": "date", "revenue": "numeric"},
    )
    category = analyze(
        "revenue by customer",
        ["customer_name", "revenue"],
        [{"customer_name": name, "revenue": 10.0} for name in "ABCDEFGH"],
        {"customer_name": "string", "revenue": "numeric"},
    )
    small_distribution = analyze(
        "vehicle status distribution",
        ["status", "count"],
        [{"status": "active", "count": 10}, {"status": "inactive", "count": 2}],
        {"status": "string", "count": "integer"},
    )
    complex_result = analyze(
        "multi-dimensional report",
        ["region", "status", "revenue", "cost"],
        [{"region": "East", "status": "active", "revenue": 10, "cost": 2}],
        {"region": "string", "status": "string", "revenue": "numeric", "cost": "numeric"},
    )

    assert (
        selector.select(
            "monthly revenue",
            ["month", "revenue"],
            time_series_rows := [{"month": "2025-01-01T00:00:00+00:00", "revenue": 10.0}],
            time_series,
        ).type
        == "line"
    )
    assert (
        selector.select(
            "revenue by customer",
            ["customer_name", "revenue"],
            [{"customer_name": name, "revenue": 10.0} for name in "ABCDEFGH"],
            category,
        ).type
        == "bar"
    )
    assert (
        selector.select(
            "status distribution",
            ["status", "count"],
            [{"status": "active", "count": 10}, {"status": "inactive", "count": 2}],
            small_distribution,
        ).type
        == "pie"
    )
    assert (
        selector.select(
            "report",
            ["region", "status", "revenue", "cost"],
            [{"region": "East", "status": "active", "revenue": 10, "cost": 2}],
            complex_result,
        ).type
        == "table"
    )
    assert time_series_rows


def test_visualization_invalid_fields_fall_back_to_table() -> None:
    invalid = selector.validate(
        Visualization(
            type="bar",
            title="Invalid",
            x_axis=VisualizationAxis("missing"),
            y_axis=VisualizationAxis("value", "decimal"),
        ),
        ["value"],
        [{"value": 1}],
    )

    assert invalid.type == "table"


def test_empty_results_and_data_quality_warnings() -> None:
    analysis = analyze(
        "show vehicles", ["vehicle_id", "status"], [], {"vehicle_id": "integer", "status": "string"}
    )

    assert analysis.kpi is None
    assert analysis.warnings == ["The query returned no records."]
    assert selector.select("show vehicles", ["vehicle_id", "status"], [], analysis).type == "table"
    assert (
        ResultSummaryService().summarize("show vehicles", "SELECT", [], [], analysis)
        == "No records matched the requested criteria."
    )


def test_result_formatting_preserves_machine_safe_values() -> None:
    assert normalize_value(Decimal("12.50")) == 12.5
    assert normalize_value(datetime(2025, 1, 1, tzinfo=UTC)) == "2025-01-01T00:00:00+00:00"
    assert (
        normalize_value(UUID("12345678-1234-5678-1234-567812345678"))
        == "12345678-1234-5678-1234-567812345678"
    )
    assert normalize_value(None) is None


def test_summary_is_grounded_and_gemini_failure_falls_back_without_summary() -> None:
    analysis = analyze(
        "top customers by revenue",
        ["customer", "revenue"],
        [{"customer": "A", "revenue": 100}, {"customer": "B", "revenue": 50}],
        {"customer": "string", "revenue": "numeric"},
    )
    deterministic = ResultSummaryService().summarize(
        "top customers by revenue",
        "SELECT",
        ["customer", "revenue"],
        [{"customer": "A", "revenue": 100}, {"customer": "B", "revenue": 50}],
        analysis,
    )
    failed_gemini = ResultSummaryService(
        gemini_summary=lambda *_: (_ for _ in ()).throw(RuntimeError("offline"))
    )

    assert deterministic == "A had the highest revenue at 100."
    assert (
        failed_gemini.summarize("question", "SELECT", ["value"], [{"value": 1}], analysis) is None
    )
