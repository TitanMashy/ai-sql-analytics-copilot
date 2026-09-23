from typing import Any

from app.services.result_models import (
    ResultAnalysis,
    Visualization,
    VisualizationAxis,
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
            return self.validate(
                Visualization(
                    type="line",
                    title="Trend",
                    x_axis=VisualizationAxis(datetime_columns[0].name, "text"),
                    y_axis=VisualizationAxis(numeric_columns[0].name, numeric_columns[0].format),
                ),
                columns,
                rows,
            )
        if categorical_columns and numeric_columns:
            category = categorical_columns[0]
            distinct_count = len({row.get(category.name) for row in rows})
            chart_type = "pie" if distinct_count <= 6 else "bar"
            return self.validate(
                Visualization(
                    type=chart_type,
                    title=self._title(question, category.name, numeric_columns[0].name),
                    x_axis=VisualizationAxis(category.name, "text"),
                    y_axis=VisualizationAxis(numeric_columns[0].name, numeric_columns[0].format),
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
        fields = {axis.field for axis in (visualization.x_axis, visualization.y_axis) if axis}
        if not fields.issubset(columns):
            return Visualization(type="table", title="Query results")
        return visualization

    @staticmethod
    def _title(question: str, category: str, numeric: str) -> str:
        if question.strip():
            return question.strip().rstrip("?").capitalize()
        return f"{category.replace('_', ' ').title()} by {numeric.replace('_', ' ').title()}"
