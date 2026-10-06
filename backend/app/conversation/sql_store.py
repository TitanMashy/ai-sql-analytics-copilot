"""PostgreSQL-backed conversation store, shared by every backend replica.

Selected with ``CONVERSATION_STORE=postgres``. Conversations and their turns survive restarts and
rolling deploys, ownership is enforced exactly as in the in-process store, and a retention job
(``python -m app.jobs.purge``) removes conversations idle longer than ``CONVERSATION_TTL_DAYS``.
Turns store the SQL and tables of assistant answers so follow-up questions can build on them;
they never store result rows.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.conversation.service import (
    ConversationAccessError,
    ConversationSession,
    ConversationStore,
    ConversationTurn,
)
from app.db.operational import ConversationRecord, ConversationTurnRecord


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as the UTC values they were stored as."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class SqlConversationStore(ConversationStore):
    def __init__(
        self,
        session_factory: Callable[[], Session],
        max_turns: int = 8,
        max_chars: int = 2000,
        max_sessions_per_owner: int = 200,
        ttl_days: int = 30,
    ) -> None:
        self._session_factory = session_factory
        self.max_turns = max_turns
        self.max_chars = max_chars
        self.max_sessions_per_owner = max_sessions_per_owner
        self.ttl = timedelta(days=ttl_days)

    # -- session lifecycle -------------------------------------------------------------------

    def create_session(self, conversation_id: str | None = None, owner: str | None = None) -> str:
        session_id = conversation_id or str(uuid4())
        owner_key = owner or ""
        try:
            with self._session_factory() as session, session.begin():
                self._ensure(session, session_id, owner_key)
        except IntegrityError:
            # Another replica created the same id between our read and write; check ownership.
            with self._session_factory() as session:
                record = session.get(ConversationRecord, session_id)
                if record is None or record.owner != owner_key:
                    raise ConversationAccessError(session_id) from None
        return session_id

    def assert_access(self, conversation_id: str, owner: str | None = None) -> None:
        with self._session_factory() as session:
            record = session.get(ConversationRecord, conversation_id)
            if record is not None and record.owner != (owner or ""):
                raise ConversationAccessError(conversation_id)

    def get_session(
        self, conversation_id: str, owner: str | None = None
    ) -> ConversationSession | None:
        with self._session_factory() as session:
            record = session.get(ConversationRecord, conversation_id)
            if record is None or record.owner != (owner or "") or self._expired(record):
                return None
            turns = self._load_turns(session, conversation_id)
            return ConversationSession(
                conversation_id=conversation_id,
                owner=owner,
                turns=turns,
                created_at=_aware(record.created_at),
                updated_at=_aware(record.updated_at),
            )

    def delete_session(self, conversation_id: str, owner: str | None = None) -> bool:
        with self._session_factory() as session, session.begin():
            record = session.get(ConversationRecord, conversation_id)
            if record is None:
                return False
            if record.owner != (owner or ""):
                raise ConversationAccessError(conversation_id)
            self._delete_conversations(session, [conversation_id])
            return True

    def purge_expired(self) -> int:
        cutoff = datetime.now(UTC) - self.ttl
        with self._session_factory() as session, session.begin():
            expired = list(
                session.scalars(
                    select(ConversationRecord.id).where(ConversationRecord.updated_at < cutoff)
                )
            )
            self._delete_conversations(session, expired)
            return len(expired)

    def count_active(self) -> int:
        cutoff = datetime.now(UTC) - self.ttl
        with self._session_factory() as session:
            return session.scalar(
                select(func.count())
                .select_from(ConversationRecord)
                .where(ConversationRecord.updated_at >= cutoff)
            ) or 0

    # -- turns -------------------------------------------------------------------------------

    def get_history(self, conversation_id: str, owner: str | None = None) -> list[ConversationTurn]:
        session_view = self.get_session(conversation_id, owner)
        return list(session_view.turns) if session_view else []

    def add_turn(
        self,
        conversation_id: str,
        role: str,
        content: str,
        owner: str | None = None,
        sql: str | None = None,
        tables: tuple[str, ...] | list[str] = (),
    ) -> ConversationTurn:
        owner_key = owner or ""
        turn = ConversationTurn(role=role, content=content, sql=sql, tables=tuple(tables))
        # A concurrent replica can create the same conversation between our read and write; the
        # second attempt then finds it and applies the ownership check.
        for _attempt in range(2):
            now = datetime.now(UTC)
            try:
                with self._session_factory() as session, session.begin():
                    record = self._ensure(session, conversation_id, owner_key)
                    record.updated_at = now
                    session.add(
                        ConversationTurnRecord(
                            conversation_id=conversation_id,
                            role=turn.role,
                            content=turn.content,
                            sql=turn.sql,
                            tables=",".join(turn.tables) or None,
                            created_at=now,
                        )
                    )
                    session.flush()
                    self._trim_turns(session, conversation_id)
                return turn
            except IntegrityError:
                continue
        raise ConversationAccessError(conversation_id)

    # -- internals ---------------------------------------------------------------------------

    def _ensure(self, session: Session, conversation_id: str, owner_key: str) -> ConversationRecord:
        """Return the conversation, creating it (or replacing an expired one) when needed."""
        record = session.get(ConversationRecord, conversation_id)
        if record is not None and self._expired(record):
            # Detach before the bulk delete so a replacement row with the same id can be added.
            session.expunge(record)
            self._delete_conversations(session, [conversation_id])
            record = None
        if record is not None:
            if record.owner != owner_key:
                raise ConversationAccessError(conversation_id)
            return record
        self._enforce_owner_cap(session, owner_key)
        now = datetime.now(UTC)
        record = ConversationRecord(
            id=conversation_id, owner=owner_key, created_at=now, updated_at=now
        )
        session.add(record)
        session.flush()
        return record

    def _enforce_owner_cap(self, session: Session, owner_key: str) -> None:
        owned = (
            session.scalar(
                select(func.count())
                .select_from(ConversationRecord)
                .where(ConversationRecord.owner == owner_key)
            )
            or 0
        )
        excess = owned - self.max_sessions_per_owner + 1
        if excess <= 0:
            return
        oldest = list(
            session.scalars(
                select(ConversationRecord.id)
                .where(ConversationRecord.owner == owner_key)
                .order_by(ConversationRecord.updated_at.asc())
                .limit(excess)
            )
        )
        self._delete_conversations(session, oldest)

    def _trim_turns(self, session: Session, conversation_id: str) -> None:
        stale = list(
            session.scalars(
                select(ConversationTurnRecord.id)
                .where(ConversationTurnRecord.conversation_id == conversation_id)
                .order_by(ConversationTurnRecord.id.desc())
                .offset(self.max_turns)
            )
        )
        if stale:
            session.execute(
                delete(ConversationTurnRecord).where(ConversationTurnRecord.id.in_(stale))
            )

    @staticmethod
    def _delete_conversations(session: Session, conversation_ids: list[str]) -> None:
        if not conversation_ids:
            return
        # Turns are deleted explicitly so SQLite (no foreign-key enforcement by default) behaves
        # like PostgreSQL's ON DELETE CASCADE.
        session.execute(
            delete(ConversationTurnRecord).where(
                ConversationTurnRecord.conversation_id.in_(conversation_ids)
            )
        )
        session.execute(
            delete(ConversationRecord).where(ConversationRecord.id.in_(conversation_ids))
        )

    def _expired(self, record: ConversationRecord) -> bool:
        return datetime.now(UTC) - _aware(record.updated_at) > self.ttl

    @staticmethod
    def _load_turns(session: Session, conversation_id: str) -> list[ConversationTurn]:
        rows = session.scalars(
            select(ConversationTurnRecord)
            .where(ConversationTurnRecord.conversation_id == conversation_id)
            .order_by(ConversationTurnRecord.id.asc())
        )
        return [
            ConversationTurn(
                role=row.role,  # type: ignore[arg-type]
                content=row.content,
                sql=row.sql,
                tables=tuple(filter(None, (row.tables or "").split(","))),
            )
            for row in rows
        ]
