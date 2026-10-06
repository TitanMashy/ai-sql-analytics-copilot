"""Operational tables: durable conversations and the audit trail.

They live on their own declarative base, separate from the fleet-analytics models in
``app.models.entities``. ``get_schema_metadata()`` (and therefore the SQL allowlist, the prompt
schema, and the ``analytics`` views) is built from ``Base.metadata`` only, so nothing here can
become queryable by generated SQL. The ``analytics_readonly`` role has no privileges on these
tables either.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class OperationalBase(DeclarativeBase):
    pass


class ConversationRecord(OperationalBase):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_owner_updated_at", "owner", "updated_at"),
        Index("ix_conversations_updated_at", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    # The authenticated principal's id. Empty only for unauthenticated development sessions.
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationTurnRecord(OperationalBase):
    __tablename__ = "conversation_turns"
    __table_args__ = (Index("ix_conversation_turns_conversation_id", "conversation_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sql: Mapped[str | None] = mapped_column(Text)
    # Comma-separated table names; the names come from the fixed analytics schema.
    tables: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditRecord(OperationalBase):
    """One row per audited event. Holds identifiers and hashes, never question or SQL text."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_occurred_at", "occurred_at"),
        Index("ix_audit_log_principal_occurred_at", "principal", "occurred_at"),
        Index("ix_audit_log_request_id", "request_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    principal: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(Integer)
    conversation_id: Mapped[str | None] = mapped_column(String(128))
    sql_hash: Mapped[str | None] = mapped_column(String(64))
    tables: Mapped[str | None] = mapped_column(String(500))
    row_count: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    helpful: Mapped[bool | None] = mapped_column(Boolean)
