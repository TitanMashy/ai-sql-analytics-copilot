from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from app.conversation.service import ConversationMemory, get_conversation_memory
from app.schemas.conversation import (
    ConversationResponse,
    ConversationTurnRequest,
    ConversationTurnResponse,
)

router = APIRouter(prefix="/analytics/conversations", tags=["conversation"])


@router.post("", response_model=ConversationResponse)
def create_conversation(
    request: Request,
    memory: ConversationMemory = Depends(get_conversation_memory),  # noqa: B008
) -> ConversationResponse:
    conversation_id = str(uuid4())
    request.state.conversation_id = conversation_id
    memory.create_session(conversation_id)
    return ConversationResponse(
        conversation_id=conversation_id,
        turns=[],
        context="No prior conversation context.",
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    request: Request,
    conversation_id: str,
    memory: ConversationMemory = Depends(get_conversation_memory),  # noqa: B008
) -> ConversationResponse:
    request.state.conversation_id = conversation_id
    session = memory.get_session(conversation_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    turns = [
        ConversationTurnResponse(
            conversation_id=conversation_id,
            role=turn.role,
            content=turn.content,
        )
        for turn in session.turns
    ]
    return ConversationResponse(
        conversation_id=conversation_id,
        turns=turns,
        context=memory.build_context(conversation_id),
    )


@router.post("/{conversation_id}/turns", response_model=ConversationTurnResponse)
def append_turn(
    request: Request,
    conversation_id: str,
    payload: ConversationTurnRequest,
    memory: ConversationMemory = Depends(get_conversation_memory),  # noqa: B008
) -> ConversationTurnResponse:
    request.state.conversation_id = conversation_id
    if memory.get_session(conversation_id) is None:
        memory.create_session(conversation_id)
    turn = memory.add_turn(conversation_id, payload.role, payload.content)
    return ConversationTurnResponse(
        conversation_id=conversation_id,
        role=turn.role,
        content=turn.content,
    )
