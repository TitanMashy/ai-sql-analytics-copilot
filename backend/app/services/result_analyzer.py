import re
from datetime import date, datetime
from typing import Any

from app.services.result_models import (
    KPI,
    ColumnProfile,
    ResultAnalysis,
    ValueFormat,
)


COUNT_TOKENS = frozenset({"count", "number", "num", "qty", "quantity"})
CURRENCY_TOKENS = frozenset(
    {"revenue", "cost", "amount", "price", "spend", "fee", "fees", "balance", "income", "sales"}
)
PERCENT_TOKENS = frozenset({"percent", "percentage", "pct", "ratio", "rate"})


def _name_tokens(column: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", column.casefold()) if token}


class AnalyticsResultAnalyzer:
    def analyze(
        self,
        question: str,
        sql: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        execution_time_ms: float,
        row_count: int,
        column_types: dict[str, str] | None = None,
    ) -> ResultAnalysis:
        del sql, execution_time_ms
        types = column_types or {}
        profiles = tuple(
            self._profile_column(question, column, rows, types.get(column, "unknown"))
            for column in columns
        )
        warnings: list[str] = []
        if row_count == 0:
            warnings.append("The query returned no records.")
        for profile in profiles:
            if profile.nullable_fraction >= 0.5:
                warnings.append(f"Column '{profile.name}' contains many NULL values.")
        kpi = self._detect_kpi(question, profiles, rows)
        return ResultAnalysis(profiles=profiles, kpi=kpi, visualization=None, warnings=warnings)

    def _profile_column(
        self,
        question: str,
        column: str,
        rows: list[dict[str, Any]],
        declared_type: str,
    ) -> ColumnProfile:
        values = [row.get(column) for row in rows]
        non_null = [value for value in values if value is not None]
        normalized_name = column.casefold()
        format_type = self._format_for(column, declared_type)
        is_identifier = (
            normalized_name == "id"
            or normalized_name.endswith("_id")
            or normalized_name.endswith("_number")
            or normalized_name in {"uuid", "license_number", "registration_number"}
        )
        is_datetime = declared_type in {"date", "datetime", "timestamp"} or any(
            self._is_datetime(value) for value in non_null
        )
        is_numeric = declared_type in {"integer", "numeric", "float", "decimal"} or (
            bool(non_null)
            and all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in non_null
            )
        )
        if is_identifier:
            kind = "identifier"
        elif is_datetime:
            kind = "datetime"
        elif is_numeric:
            kind = "numeric"
        elif non_null and all(isinstance(value, str) for value in non_null):
            kind = "categorical"
        else:
            kind = "unknown"
        return ColumnProfile(
            name=column,
            kind=kind,
            data_type=declared_type,
            nullable_fraction=1 - (len(non_null) / len(values)) if values else 0,
            format=format_type,
            aggregate_like=self._looks_aggregated(column),
        )

    def _detect_kpi(
        self,
        question: str,
        profiles: tuple[ColumnProfile, ...],
        rows: list[dict[str, Any]],
    ) -> KPI | None:
        """A KPI is a single row with a single numeric measure, regardless of question wording."""
        if len(rows) != 1:
            return None
        if any(profile.kind in {"datetime", "categorical"} for profile in profiles):
            return None
        candidates = [
            profile
            for profile in profiles
            if profile.kind == "numeric" and not profile.name.casefold().endswith("_id")
        ]
        if len(candidates) != 1:
            return None
        candidate = candidates[0]
        return KPI(
            label=self._kpi_label(question, candidate.name),
            value=rows[0].get(candidate.name),
            format=candidate.format,
        )

    @staticmethod
    def _kpi_label(question: str, column: str) -> str:
        if "revenue" in question.casefold():
            return "Total Revenue"
        if "active vehicle" in question.casefold():
            return "Active Vehicles"
        if "average" in question.casefold() or "avg" in question.casefold():
            return column.replace("_", " ").title()
        return column.replace("_", " ").title()

    @staticmethod
    def _format_for(column: str, declared_type: str = "unknown") -> ValueFormat:
        """Choose a display format from the column's name and type only.

        The question text is deliberately ignored: a question that mentions "revenue" must not
        turn every column into currency, and substrings such as ``rate`` inside ``generated``
        must not count, so the column name is compared token by token.
        """
        tokens = _name_tokens(column)
        if tokens & COUNT_TOKENS:
            return "integer"
        if tokens & CURRENCY_TOKENS:
            return "currency"
        if tokens & PERCENT_TOKENS:
            return "percentage"
        if declared_type == "integer":
            return "integer"
        return "decimal"

    @staticmethod
    def _looks_aggregated(column: str) -> bool:
        return any(
            token in column.casefold()
            for token in (
                "count",
                "sum",
                "total",
                "avg",
                "average",
                "min",
                "max",
                "revenue",
                "cost",
            )
        )

    @staticmethod
    def _is_datetime(value: Any) -> bool:
        if isinstance(value, (date, datetime)):
            return True
        if isinstance(value, str):
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                return "-" in value or "T" in value
            except ValueError:
                return False
        return False
