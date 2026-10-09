import json
import logging
from datetime import UTC, datetime


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in (
            "request_id",
            "conversation_id",
            "endpoint",
            "execution_time_ms",
            "request_duration_ms",
            "llm_latency_ms",
            "sql_validation_duration_ms",
            "sql_execution_duration_ms",
            "result_row_count",
            "validation_status",
            "repair_count",
            "provider_status_code",
            "error_type",
            "status_code",
            "event",
            "outcome",
            "principal",
            "customer_id",
            "sql_hash",
            "tables",
            "duration_ms",
            "helpful",
            "error_code",
        ):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)


def configure_logging(log_level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        handlers=[handler],
        force=True,
    )
