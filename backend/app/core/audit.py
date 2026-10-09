"""Audit trail: who asked what kind of question, what ran, and what came back, without content.

An :class:`AuditEvent` holds identifiers, a SHA-256 of the SQL, table names, counts, and an
outcome. It deliberately has no field for the question text, the SQL text, result rows, or
credentials, so no sink can record them. Reviewers can correlate an event with an application log
line or a support ticket by ``request_id`` and compare ``sql_hash`` values to spot repeated or
unusual queries.

Sinks (``AUDIT_SINK``): ``log`` writes a structured JSON line on the ``audit`` logger (ship it to
your log store); ``database`` inserts into ``audit_log``; ``both`` does both. A failing sink never
fails the request.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.operational import AuditRecord

audit_logger = logging.getLogger("audit")
logger = logging.getLogger(__name__)


def hash_sql(sql: str) -> str:
    """Stable fingerprint of a statement (whitespace-insensitive) that does not reveal it."""
    return hashlib.sha256(" ".join(sql.split()).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditEvent:
    event: str  # "ask" or "feedback"
    outcome: str  # "success", "error", "helpful", "not_helpful"
    request_id: str | None
    principal: str
    customer_id: int | None = None
    conversation_id: str | None = None
    sql_hash: str | None = None
    tables: tuple[str, ...] = ()
    row_count: int | None = None
    duration_ms: float | None = None
    error_code: str | None = None
    helpful: bool | None = None


class LogAuditSink:
    def write(self, event: AuditEvent) -> None:
        audit_logger.info(
            "audit event",
            extra={
                "event": event.event,
                "outcome": event.outcome,
                "request_id": event.request_id,
                "principal": event.principal,
                "customer_id": event.customer_id,
                "conversation_id": event.conversation_id,
                "sql_hash": event.sql_hash,
                "tables": list(event.tables),
                "result_row_count": event.row_count,
                "duration_ms": None if event.duration_ms is None else round(event.duration_ms, 2),
                "error_code": event.error_code,
                "helpful": event.helpful,
            },
        )


class DatabaseAuditSink:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def write(self, event: AuditEvent) -> None:
        with self._session_factory() as session, session.begin():
            session.add(
                AuditRecord(
                    occurred_at=datetime.now(UTC),
                    event=event.event,
                    request_id=event.request_id,
                    principal=event.principal,
                    customer_id=event.customer_id,
                    conversation_id=event.conversation_id,
                    sql_hash=event.sql_hash,
                    tables=",".join(event.tables) or None,
                    row_count=event.row_count,
                    duration_ms=event.duration_ms,
                    outcome=event.outcome,
                    error_code=event.error_code,
                    helpful=event.helpful,
                )
            )


class AuditService:
    def __init__(self, sinks: Sequence[LogAuditSink | DatabaseAuditSink]) -> None:
        self.sinks = tuple(sinks)

    def record(self, event: AuditEvent) -> None:
        for sink in self.sinks:
            try:
                sink.write(event)
            except Exception as error:  # an audit failure must never fail the request
                logger.error(
                    "audit sink failed",
                    extra={"error_type": type(error).__name__, "request_id": event.request_id},
                )


@lru_cache
def get_audit_service() -> AuditService:
    settings = get_settings()
    sinks: list[LogAuditSink | DatabaseAuditSink] = []
    if settings.audit_sink in {"log", "both"}:
        sinks.append(LogAuditSink())
    if settings.audit_sink in {"database", "both"}:
        from app.db.session import SessionLocal

        sinks.append(DatabaseAuditSink(SessionLocal))
    return AuditService(sinks)


def purge_audit_records(session_factory: Callable[[], Session], retention_days: int) -> int:
    """Delete audit rows older than the retention period; returns how many were removed."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    with session_factory() as session, session.begin():
        result = session.execute(delete(AuditRecord).where(AuditRecord.occurred_at < cutoff))
        return getattr(result, "rowcount", 0) or 0
