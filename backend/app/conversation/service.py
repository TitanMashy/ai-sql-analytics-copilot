from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4


@dataclass(frozen=True)
class ConversationTurn:
    role: Literal["user", "assistant", "system"]
    content: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", self.role.lower())
        object.__setattr__(self, "content", self.content.strip())


@dataclass
class ConversationSession:
    conversation_id: str
    turns: list[ConversationTurn] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def add_turn(self, role: str, content: str) -> ConversationTurn:
        turn = ConversationTurn(role=role, content=content)
        self.turns.append(turn)
        self.updated_at = datetime.now(UTC)
        return turn


class ConversationMemory:
    def __init__(self, max_turns: int = 8, max_chars: int = 2000) -> None:
        self.max_turns = max_turns
        self.max_chars = max_chars
        self._sessions: dict[str, ConversationSession] = defaultdict(ConversationSession)

    @staticmethod
    def default() -> ConversationMemory:
        return get_conversation_memory()

    def create_session(self, conversation_id: str | None = None) -> str:
        session_id = conversation_id or str(uuid4())
        self._sessions.setdefault(session_id, ConversationSession(conversation_id=session_id))
        return session_id

    def get_or_create(self, conversation_id: str | None = None) -> str:
        return self.create_session(conversation_id)

    def get_history(self, conversation_id: str) -> list[ConversationTurn]:
        session = self._sessions.get(conversation_id)
        if session is None:
            return []
        return list(session.turns)

    def add_turn(
        self,
        conversation_id: str,
        role: str,
        content: str,
    ) -> ConversationTurn:
        session = self._sessions.setdefault(
            conversation_id,
            ConversationSession(conversation_id=conversation_id),
        )
        turn = session.add_turn(role, content)
        if len(session.turns) > self.max_turns:
            session.turns = session.turns[-self.max_turns :]
        return turn

    def build_context(self, conversation_id: str) -> str:
        history = self.get_history(conversation_id)
        if not history:
            return "No prior conversation context."

        relevant = history[-self.max_turns :]
        lines = [f"{turn.role}: {turn.content}" for turn in relevant]
        context = "\n".join(lines)
        if len(context) <= self.max_chars:
            return context
        return context[-self.max_chars :]

    def get_session(self, conversation_id: str) -> ConversationSession | None:
        return self._sessions.get(conversation_id)


_default_conversation_memory = ConversationMemory()


def get_conversation_memory() -> ConversationMemory:
    return _default_conversation_memory
