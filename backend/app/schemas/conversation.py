from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ConversationTurnRequest(BaseModel):
    role: Literal["user", "assistant", "system"] = Field(default="user")
    content: str = Field(..., min_length=1)


class ConversationTurnResponse(BaseModel):
    conversation_id: str
    role: Literal["user", "assistant", "system"]
    content: str


class ConversationResponse(BaseModel):
    conversation_id: str
    turns: list[ConversationTurnResponse] = Field(default_factory=list)
    context: str | None = None
