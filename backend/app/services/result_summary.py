import re
from typing import Any

from app.services.result_models import KPI, ColumnProfile, ResultAnalysis, ValueFormat

LOWEST_PATTERN = re.compile(
    r"\b(lowest|least|bottom|fewest|smallest|minimum|worst|cheapest|shortest)\b", re.IGNORECASE
)


def format_value(value: Any, value_format: ValueFormat) -> str:
    """Render a number according to its column format (plain text, no currency symbol)."""
    if value is None:
        return "no value"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if value_format == "currency":
        return f"{number:,.2f}"
    if value_format == "integer":
        return f"{int(number):,}"
    if value_format == "percentage":
        return f"{number:.2f}%"
    text = f"{number:,.2f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


class ResultSummaryService:
    """Deterministic, row-grounded summaries. Nothing here calls an LLM."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def summarize(
        self,
        question: str,
        sql: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        analysis: ResultAnalysis,
    ) -> str | None:
        del sql, columns
        if not self.enabled:
            return None
        if not rows:
            return "No records matched the requested criteria."
        if analysis.kpi is not None:
            return f"{analysis.kpi.label}: {self._format_kpi(analysis.kpi)}."
        return self._deterministic_summary(question, rows, analysis)

    @staticmethod
    def _deterministic_summary(
        question: str, rows: list[dict[str, Any]], analysis: ResultAnalysis
    ) -> str:
        numeric = next(
            (profile for profile in analysis.profiles if profile.kind == "numeric"), None
        )
        category = next(
            (profile for profile in analysis.profiles if profile.kind == "categorical"), None
        )
        count_text = f"{len(rows)} record" + ("" if len(rows) == 1 else "s")
        if numeric is None or category is None:
            return f"The query returned {count_text}."
        measured = [row for row in rows if _is_number(row.get(numeric.name))]
        if not measured:
            return f"The query returned {count_text}."
        lowest = bool(LOWEST_PATTERN.search(question))
        pick = min if lowest else max
        best_row = pick(measured, key=lambda row: float(row[numeric.name]))
        return (
            f"{best_row.get(category.name)} had the {'lowest' if lowest else 'highest'} "
            f"{_metric_label(numeric)} at {format_value(best_row[numeric.name], numeric.format)}."
        )

    @staticmethod
    def _format_kpi(kpi: KPI) -> str:
        return format_value(kpi.value, kpi.format)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _metric_label(profile: ColumnProfile) -> str:
    return profile.name.replace("_", " ")
