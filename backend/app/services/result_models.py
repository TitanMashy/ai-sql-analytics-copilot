from dataclasses import dataclass
from typing import Any, Literal

ValueFormat = Literal["currency", "integer", "decimal", "percentage", "text"]
VisualizationType = Literal["table", "kpi", "bar", "line", "area", "pie"]


@dataclass(frozen=True)
class KPI:
    label: str
    value: Any
    format: ValueFormat


@dataclass(frozen=True)
class VisualizationAxis:
    field: str
    format: ValueFormat = "text"


@dataclass(frozen=True)
class Visualization:
    type: VisualizationType
    title: str
    x_axis: VisualizationAxis | None = None
    y_axis: VisualizationAxis | None = None


@dataclass(frozen=True)
class ResultAnalysis:
    profiles: tuple["ColumnProfile", ...]
    kpi: KPI | None
    visualization: Visualization | None
    warnings: list[str]


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    kind: Literal["numeric", "categorical", "datetime", "identifier", "unknown"]
    data_type: str
    nullable_fraction: float
    format: ValueFormat
    aggregate_like: bool
