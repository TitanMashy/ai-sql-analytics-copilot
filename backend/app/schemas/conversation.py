from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings


class ConversationTurnRequest(BaseModel):
    role: Literal["user", "assistant", "system"] = Field(default="user")
    content: str = Field(..., min_length=1, max_length=10000)

    @field_validator("content")
    @classmethod
    def enforce_content_limit(cls, value: str) -> str:
        if len(value) > get_settings().max_conversation_context_chars:
            raise ValueError("Conversation turn exceeds the configured length limit.")
        return value


class ConversationTurnResponse(BaseModel):
    conversation_id: str
    role: Literal["user", "assistant", "system"]
    content: str


class ConversationResponse(BaseModel):
    conversation_id: str
    turns: list[ConversationTurnResponse] = Field(default_factory=list)
    context: str | None = None
