from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from threading import RLock
from typing import Literal
from uuid import uuid4

MAX_SQL_CHARS_IN_CONTEXT = 600


class ConversationAccessError(LookupError):
    """The conversation does not exist for this caller.

    Raised both for unknown ids and for conversations owned by someone else, so a caller cannot
    distinguish "not mine" from "not found".
    """


@dataclass(frozen=True)
class ConversationTurn:
    role: Literal["user", "assistant", "system"]
    content: str
    sql: str | None = None
    tables: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", self.role.lower())
        object.__setattr__(self, "content", self.content.strip())
        object.__setattr__(self, "tables", tuple(self.tables))


@dataclass
class ConversationSession:
    conversation_id: str
    owner: str | None = None
    turns: list[ConversationTurn] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def add_turn(
        self,
        role: str,
        content: str,
        sql: str | None = None,
        tables: tuple[str, ...] | list[str] = (),
    ) -> ConversationTurn:
        turn = ConversationTurn(role=role, content=content, sql=sql, tables=tuple(tables))
        self.turns.append(turn)
        self.updated_at = datetime.now(UTC)
        return turn


class ConversationStore:
    """The interface every conversation store implements, plus the shared context builder.

    ``ConversationMemory`` (in process) is the default and the test double;
    ``SqlConversationStore`` (PostgreSQL) is the durable implementation that several replicas can
    share. Both enforce the same ownership rule: a conversation belongs to the principal that
    created it, and anyone else sees it as missing.
    """

    max_turns: int
    max_chars: int

    def create_session(self, conversation_id: str | None = None, owner: str | None = None) -> str:
        raise NotImplementedError

    def get_or_create(self, conversation_id: str | None = None, owner: str | None = None) -> str:
        return self.create_session(conversation_id, owner)

    def assert_access(self, conversation_id: str, owner: str | None = None) -> None:
        raise NotImplementedError

    def get_session(
        self, conversation_id: str, owner: str | None = None
    ) -> ConversationSession | None:
        raise NotImplementedError

    def get_history(self, conversation_id: str, owner: str | None = None) -> list[ConversationTurn]:
        raise NotImplementedError

    def add_turn(
        self,
        conversation_id: str,
        role: str,
        content: str,
        owner: str | None = None,
        sql: str | None = None,
        tables: tuple[str, ...] | list[str] = (),
    ) -> ConversationTurn:
        raise NotImplementedError

    def delete_session(self, conversation_id: str, owner: str | None = None) -> bool:
        """Delete a conversation. False when it does not exist; raises when it is not yours."""
        raise NotImplementedError

    def purge_expired(self) -> int:
        """Remove conversations idle past the retention period; returns how many."""
        raise NotImplementedError

    def count_active(self) -> int:
        raise NotImplementedError

    def build_context(self, conversation_id: str, owner: str | None = None) -> str:
        history = self.get_history(conversation_id, owner)
        if not history:
            return "No prior conversation context."

        lines = [self._format_turn(turn) for turn in history[-self.max_turns :]]
        # Keep whole turns, newest first, until the character budget is spent.
        kept: list[str] = []
        used = 0
        for line in reversed(lines):
            cost = len(line) + (1 if kept else 0)
            if used + cost > self.max_chars:
                break
            kept.append(line)
            used += cost
        if not kept:
            return lines[-1][-self.max_chars :]
        return "\n".join(reversed(kept))

    @staticmethod
    def _format_turn(turn: ConversationTurn) -> str:
        line = f"{turn.role}: {turn.content}"
        if turn.sql:
            sql = (
                turn.sql
                if len(turn.sql) <= MAX_SQL_CHARS_IN_CONTEXT
                else turn.sql[:MAX_SQL_CHARS_IN_CONTEXT] + "..."
            )
            line += f"\n  SQL: {sql}"
        if turn.tables:
            line += f"\n  Tables: {', '.join(turn.tables)}"
        return line


class ConversationMemory(ConversationStore):
    """Process-local, bounded, owner-scoped conversation store.

    Every session belongs to the principal that created it. Reads and writes by anyone else look
    like a missing conversation. Sessions expire after ``ttl_seconds`` of inactivity and the store
    is capped globally and per owner, so a client cannot grow memory without bound.
    """

    def __init__(
        self,
        max_turns: int = 8,
        max_chars: int = 2000,
        max_sessions: int = 10_000,
        max_sessions_per_owner: int = 200,
        ttl_seconds: float = 24 * 60 * 60,
    ) -> None:
        self.max_turns = max_turns
        self.max_chars = max_chars
        self.max_sessions = max_sessions
        self.max_sessions_per_owner = max_sessions_per_owner
        self.ttl = timedelta(seconds=ttl_seconds)
        self._sessions: dict[str, ConversationSession] = {}
        self._lock = RLock()

    @staticmethod
    def default() -> ConversationMemory:
        store = get_conversation_memory()
        return store  # type: ignore[return-value]

    # -- session lifecycle -------------------------------------------------------------------

    def create_session(self, conversation_id: str | None = None, owner: str | None = None) -> str:
        with self._lock:
            session_id = conversation_id or str(uuid4())
            existing = self._sessions.get(session_id)
            if existing is not None:
                self._require_owner(existing, owner)
                return session_id
            self._evict(owner)
            self._sessions[session_id] = ConversationSession(
                conversation_id=session_id, owner=owner
            )
            return session_id

    def assert_access(self, conversation_id: str, owner: str | None = None) -> None:
        """Raise unless the conversation is absent or belongs to ``owner``."""
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is not None:
                self._require_owner(session, owner)

    def get_session(
        self, conversation_id: str, owner: str | None = None
    ) -> ConversationSession | None:
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is None or session.owner != owner or self._expired(session):
                return None
            return session

    def delete_session(self, conversation_id: str, owner: str | None = None) -> bool:
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is None:
                return False
            self._require_owner(session, owner)
            del self._sessions[conversation_id]
            return True

    def purge_expired(self) -> int:
        with self._lock:
            expired = [key for key, item in self._sessions.items() if self._expired(item)]
            for key in expired:
                del self._sessions[key]
            return len(expired)

    def count_active(self) -> int:
        with self._lock:
            return sum(1 for item in self._sessions.values() if not self._expired(item))

    # -- turns -------------------------------------------------------------------------------

    def get_history(self, conversation_id: str, owner: str | None = None) -> list[ConversationTurn]:
        session = self.get_session(conversation_id, owner)
        if session is None:
            return []
        with self._lock:
            return list(session.turns)

    def add_turn(
        self,
        conversation_id: str,
        role: str,
        content: str,
        owner: str | None = None,
        sql: str | None = None,
        tables: tuple[str, ...] | list[str] = (),
    ) -> ConversationTurn:
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is not None and self._expired(session):
                del self._sessions[conversation_id]
                session = None
            if session is None:
                self._evict(owner)
                session = ConversationSession(conversation_id=conversation_id, owner=owner)
                self._sessions[conversation_id] = session
            else:
                self._require_owner(session, owner)
            turn = session.add_turn(role, content, sql=sql, tables=tables)
            if len(session.turns) > self.max_turns:
                session.turns = session.turns[-self.max_turns :]
            return turn

    # -- internals ---------------------------------------------------------------------------

    @staticmethod
    def _require_owner(session: ConversationSession, owner: str | None) -> None:
        if session.owner != owner:
            raise ConversationAccessError(session.conversation_id)

    def _expired(self, session: ConversationSession) -> bool:
        return datetime.now(UTC) - session.updated_at > self.ttl

    def _evict(self, owner: str | None) -> None:
        """Make room for one new session. Caller holds the lock."""
        for session_id in [key for key, item in self._sessions.items() if self._expired(item)]:
            del self._sessions[session_id]
        owned = [item for item in self._sessions.values() if item.owner == owner]
        while len(owned) >= self.max_sessions_per_owner:
            oldest = min(owned, key=lambda item: item.updated_at)
            del self._sessions[oldest.conversation_id]
            owned.remove(oldest)
        while len(self._sessions) >= self.max_sessions:
            oldest = min(self._sessions.values(), key=lambda item: item.updated_at)
            del self._sessions[oldest.conversation_id]


_default_conversation_memory = ConversationMemory()


@lru_cache
def get_conversation_memory() -> ConversationStore:
    """The conversation store selected by ``CONVERSATION_STORE``.

    ``memory`` (default) is process-local. ``postgres`` is durable and shared by every replica.
    """
    from app.core.config import get_settings

    settings = get_settings()
    if settings.conversation_store == "postgres":
        from app.conversation.sql_store import SqlConversationStore
        from app.db.session import SessionLocal

        return SqlConversationStore(
            SessionLocal,
            max_turns=settings.conversation_max_turns,
            max_chars=settings.max_conversation_context_chars,
            max_sessions_per_owner=settings.conversation_max_per_owner,
            ttl_days=settings.conversation_ttl_days,
        )
    return _default_conversation_memory
