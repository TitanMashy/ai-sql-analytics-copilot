import logging
from collections.abc import Callable
from typing import Any

from app.services.result_models import KPI, ResultAnalysis

logger = logging.getLogger(__name__)


class ResultSummaryService:
    def __init__(
        self,
        enabled: bool = True,
        gemini_summary: Callable[[str, str, list[str], list[dict[str, Any]]], str | None]
        | None = None,
    ) -> None:
        self.enabled = enabled
        self.gemini_summary = gemini_summary

    def summarize(
        self,
        question: str,
        sql: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        analysis: ResultAnalysis,
    ) -> str | None:
        if not self.enabled:
            return None
        if not rows:
            return "No records matched the requested criteria."
        if self.gemini_summary is not None:
            try:
                return self.gemini_summary(question, sql, columns, rows)
            except Exception:
                logger.exception("Gemini result summary failed")
                return None
        if analysis.kpi is not None:
            return f"{analysis.kpi.label}: {self._format_value(analysis.kpi)}."
        return self._deterministic_summary(columns, rows, analysis)

    @staticmethod
    def _deterministic_summary(
        columns: list[str], rows: list[dict[str, Any]], analysis: ResultAnalysis
    ) -> str:
        numeric = next(
            (profile for profile in analysis.profiles if profile.kind == "numeric"), None
        )
        category = next(
            (profile for profile in analysis.profiles if profile.kind == "categorical"), None
        )
        if numeric is None or category is None:
            return f"The query returned {len(rows)} records."
        best_row = max(rows, key=lambda row: row.get(numeric.name) or 0)
        return (
            f"{best_row.get(category.name)} had the highest {numeric.name.replace('_', ' ')} "
            f"at {best_row.get(numeric.name)}."
        )

    @staticmethod
    def _format_value(kpi: KPI) -> str:
        if kpi.value is None:
            return "no value"
        if kpi.format == "currency":
            return f"{float(kpi.value):,.2f}"
        if kpi.format == "integer":
            return f"{int(kpi.value):,}"
        if kpi.format == "percentage":
            return f"{float(kpi.value):.2f}%"
        return str(kpi.value)
