import re
from typing import Any

from app.services.result_models import (
    ColumnProfile,
    ResultAnalysis,
    Visualization,
    VisualizationAxis,
)

MAX_PIE_CATEGORIES = 6
# Measures whose values do not add up to a whole, so a pie of them would mislead.
NON_ADDITIVE_TOKENS = frozenset(
    {
        "avg", "average", "mean", "median", "min", "max", "rate", "ratio", "percent",
        "percentage", "pct", "per", "speed", "utilization",
    }
)


class VisualizationSelector:
    def select(
        self,
        question: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        analysis: ResultAnalysis,
    ) -> Visualization:
        if not rows:
            return Visualization(type="table", title="No results")
        if analysis.kpi is not None:
            return Visualization(type="kpi", title=analysis.kpi.label)

        datetime_columns = [profile for profile in analysis.profiles if profile.kind == "datetime"]
        numeric_columns = [
            profile
            for profile in analysis.profiles
            if profile.kind == "numeric" and not profile.name.casefold().endswith("_id")
        ]
        categorical_columns = [
            profile for profile in analysis.profiles if profile.kind == "categorical"
        ]
        if len(categorical_columns) > 1 and len(numeric_columns) > 1:
            return Visualization(type="table", title="Query results")
        if datetime_columns and numeric_columns:
            axis = datetime_columns[0]
            series = self._series(numeric_columns)
            return self.validate(
                Visualization(
                    type="line",
                    title=self._title(numeric_columns[0].name, axis.name),
                    x_axis=VisualizationAxis(axis.name, "text"),
                    y_axis=series[0],
                    series=series if len(series) > 1 else (),
                ),
                columns,
                rows,
            )
        if categorical_columns and numeric_columns:
            category = categorical_columns[0]
            series = self._series(numeric_columns)
            distinct_values = {row.get(category.name) for row in rows}
            use_pie = (
                len(series) == 1
                and len(distinct_values) <= MAX_PIE_CATEGORIES
                and self._is_additive(numeric_columns[0])
                and self._all_non_negative(rows, numeric_columns[0].name)
            )
            return self.validate(
                Visualization(
                    type="pie" if use_pie else "bar",
                    title=self._title(numeric_columns[0].name, category.name),
                    x_axis=VisualizationAxis(category.name, "text"),
                    y_axis=series[0],
                    series=series if len(series) > 1 else (),
                ),
                columns,
                rows,
            )
        return Visualization(type="table", title="Query results")

    @staticmethod
    def validate(
        visualization: Visualization,
        columns: list[str],
        rows: list[dict[str, Any]],
    ) -> Visualization:
        if not rows or visualization.x_axis is None and visualization.y_axis is None:
            return Visualization(type="table", title="Query results")
        axes = (visualization.x_axis, visualization.y_axis, *visualization.series)
        fields = {axis.field for axis in axes if axis}
        if not fields.issubset(columns):
            return Visualization(type="table", title="Query results")
        return visualization

    @staticmethod
    def _series(numeric_columns: list[ColumnProfile]) -> tuple[VisualizationAxis, ...]:
        """Plot every measure that shares the first measure's format.

        Measures with different formats (liters next to dollars) would need separate axes, so
        only the first group is charted; the result table still shows every column.
        """
        first = numeric_columns[0]
        return tuple(
            VisualizationAxis(profile.name, profile.format)
            for profile in numeric_columns
            if profile.format == first.format
        )

    @staticmethod
    def _is_additive(profile: ColumnProfile) -> bool:
        tokens = {token for token in re.split(r"[^a-z0-9]+", profile.name.casefold()) if token}
        return not tokens & NON_ADDITIVE_TOKENS

    @staticmethod
    def _all_non_negative(rows: list[dict[str, Any]], field: str) -> bool:
        for row in rows:
            value = row.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value < 0:
                return False
        return True

    @staticmethod
    def _title(measure: str, dimension: str) -> str:
        """A short chart title such as ``Total Revenue by Company Name``."""
        return f"{measure.replace('_', ' ').title()} by {dimension.replace('_', ' ').title()}"
