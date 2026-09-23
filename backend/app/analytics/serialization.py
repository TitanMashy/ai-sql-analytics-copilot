from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


def normalize_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (UUID, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    if isinstance(value, Mapping):
        return {str(key): normalize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [normalize_value(item) for item in value]
    return str(value)


def normalize_rows(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_value(dict(row)) for row in rows]
