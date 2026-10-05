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


def select(question: str, columns: list[str], rows: list[dict], types: dict[str, str]):
    analysis = analyze(question, columns, rows, types)
    return selector.select(question, columns, rows, analysis)


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


def test_kpi_is_detected_from_result_shape_not_question_wording() -> None:
    analysis = analyze(
        "How many active vehicles do we have?",
        ["active_vehicle_count"],
        [{"active_vehicle_count": 766}],
        {"active_vehicle_count": "integer"},
    )

    assert analysis.kpi is not None
    assert analysis.kpi.label == "Active Vehicles"
    assert analysis.kpi.value == 766
    assert analysis.kpi.format == "integer"


def test_kpi_requires_exactly_one_numeric_measure_in_one_row() -> None:
    two_measures = analyze(
        "Show totals",
        ["total_revenue", "invoice_count"],
        [{"total_revenue": 10.0, "invoice_count": 2}],
        {"total_revenue": "numeric", "invoice_count": "integer"},
    )
    two_rows = analyze(
        "Show totals",
        ["total_revenue"],
        [{"total_revenue": 10.0}, {"total_revenue": 12.0}],
        {"total_revenue": "numeric"},
    )

    assert two_measures.kpi is None
    assert two_rows.kpi is None


def test_formats_come_from_column_names_not_the_question() -> None:
    analysis = analyze(
        "Top 10 customers by revenue",
        ["company_name", "customer_count", "total_revenue"],
        [{"company_name": "Acme", "customer_count": 3, "total_revenue": 10.5}],
        {"company_name": "string", "customer_count": "integer", "total_revenue": "numeric"},
    )

    formats = {profile.name: profile.format for profile in analysis.profiles}
    assert formats == {
        "company_name": "decimal",
        "customer_count": "integer",
        "total_revenue": "currency",
    }


def test_format_tokens_do_not_match_inside_other_words() -> None:
    # "rate" appears inside "generated" and "operator"; neither is a rate column.
    analysis = analyze(
        "Which operators generated the most trips?",
        ["generated_total", "operator_score"],
        [{"generated_total": 4.5, "operator_score": 2.5}],
        {"generated_total": "numeric", "operator_score": "numeric"},
    )

    assert {profile.format for profile in analysis.profiles} == {"decimal"}
    percentage = analyze(
        "utilization",
        ["utilization_rate"],
        [{"utilization_rate": 0.4}],
        {"utilization_rate": "numeric"},
    )
    assert percentage.profiles[0].format == "percentage"


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


def test_pie_is_limited_to_additive_measures_and_six_categories() -> None:
    averages = select(
        "average idle by status",
        ["status", "average_idle_minutes"],
        [
            {"status": "a", "average_idle_minutes": 3.0},
            {"status": "b", "average_idle_minutes": 4.0},
        ],
        {"status": "string", "average_idle_minutes": "numeric"},
    )
    seven_categories = select(
        "count by type",
        ["vehicle_type", "vehicle_count"],
        [{"vehicle_type": f"type-{index}", "vehicle_count": index} for index in range(7)],
        {"vehicle_type": "string", "vehicle_count": "integer"},
    )
    six_categories = select(
        "count by type",
        ["vehicle_type", "vehicle_count"],
        [{"vehicle_type": f"type-{index}", "vehicle_count": index} for index in range(6)],
        {"vehicle_type": "string", "vehicle_count": "integer"},
    )
    negative = select(
        "net change by type",
        ["vehicle_type", "vehicle_count"],
        [{"vehicle_type": "a", "vehicle_count": 5}, {"vehicle_type": "b", "vehicle_count": -2}],
        {"vehicle_type": "string", "vehicle_count": "integer"},
    )

    assert averages.type == "bar"
    assert seven_categories.type == "bar"
    assert six_categories.type == "pie"
    assert negative.type == "bar"


def test_measures_with_the_same_format_become_series_on_one_chart() -> None:
    visualization = select(
        "revenue and cost by month",
        ["month", "total_revenue", "total_cost"],
        [{"month": "2025-01-01T00:00:00+00:00", "total_revenue": 10.0, "total_cost": 4.0}],
        {"month": "date", "total_revenue": "numeric", "total_cost": "numeric"},
    )

    assert visualization.type == "line"
    assert [axis.field for axis in visualization.series] == ["total_revenue", "total_cost"]
    assert visualization.y_axis == visualization.series[0]


def test_measures_with_different_formats_are_not_forced_onto_one_axis() -> None:
    visualization = select(
        "fuel consumption by manufacturer",
        ["manufacturer", "total_liters", "total_fuel_cost"],
        [
            {"manufacturer": f"maker-{index}", "total_liters": 100.0, "total_fuel_cost": 150.0}
            for index in range(8)
        ],
        {"manufacturer": "string", "total_liters": "numeric", "total_fuel_cost": "numeric"},
    )

    assert visualization.type == "bar"
    assert visualization.y_axis.field == "total_liters"
    assert visualization.series == ()


def test_chart_titles_are_short_and_not_the_whole_question() -> None:
    visualization = select(
        "Please show me the revenue by customer for every single customer this year",
        ["company_name", "total_revenue"],
        [{"company_name": name, "total_revenue": 1.0} for name in "ABCDEFGH"],
        {"company_name": "string", "total_revenue": "numeric"},
    )

    assert visualization.title == "Total Revenue by Company Name"


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
    invalid_series = selector.validate(
        Visualization(
            type="bar",
            title="Invalid series",
            x_axis=VisualizationAxis("value"),
            y_axis=VisualizationAxis("value", "decimal"),
            series=(VisualizationAxis("ghost", "decimal"),),
        ),
        ["value"],
        [{"value": 1}],
    )

    assert invalid.type == "table"
    assert invalid_series.type == "table"


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


CUSTOMER_ROWS = [{"customer": "A", "revenue": 100}, {"customer": "B", "revenue": 50}]
CUSTOMER_TYPES = {"customer": "string", "revenue": "numeric"}


def _summary(question: str, rows: list[dict] | None = None) -> str | None:
    rows = rows or CUSTOMER_ROWS
    analysis = analyze(question, ["customer", "revenue"], rows, CUSTOMER_TYPES)
    return ResultSummaryService().summarize(
        question, "SELECT", ["customer", "revenue"], rows, analysis
    )


def test_summary_is_grounded_and_uses_the_column_format() -> None:
    assert _summary("top customers by revenue") == "A had the highest revenue at 100.00."


def test_summary_respects_lowest_questions() -> None:
    lowest = _summary("which customer has the lowest revenue?")
    assert lowest == "B had the lowest revenue at 50.00."
    assert _summary("bottom customers by revenue") == "B had the lowest revenue at 50.00."


def test_summary_ignores_rows_without_a_numeric_value() -> None:
    rows = [{"customer": "A", "revenue": None}, {"customer": "B", "revenue": 50}]

    assert _summary("top customers", rows) == "B had the highest revenue at 50.00."


def test_kpi_summary_formats_the_value() -> None:
    analysis = analyze(
        "total revenue",
        ["total_revenue"],
        [{"total_revenue": 1254300.0}],
        {"total_revenue": "numeric"},
    )

    summary = ResultSummaryService().summarize(
        "total revenue", "SELECT", ["total_revenue"], [{"total_revenue": 1254300.0}], analysis
    )

    assert summary == "Total Revenue: 1,254,300.00."


def test_summary_can_be_disabled() -> None:
    analysis = analyze("q", ["customer", "revenue"], CUSTOMER_ROWS, CUSTOMER_TYPES)

    assert (
        ResultSummaryService(enabled=False).summarize(
            "q", "SELECT", ["customer", "revenue"], CUSTOMER_ROWS, analysis
        )
        is None
    )
