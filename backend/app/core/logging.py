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
            "endpoint",
            "execution_time_ms",
            "result_row_count",
            "validation_status",
            "status_code",
        ):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(log_level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        handlers=[handler],
        force=True,
    )
