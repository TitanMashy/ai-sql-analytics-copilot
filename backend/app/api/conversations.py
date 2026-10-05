from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from app.conversation.service import (
    ConversationAccessError,
    ConversationMemory,
    get_conversation_memory,
)
from app.core.auth import Principal, get_principal
from app.core.rate_limit import enforce_rate_limit
from app.schemas.conversation import (
    ConversationResponse,
    ConversationTurnRequest,
    ConversationTurnResponse,
)

# Conversations belong to the principal that created them; anyone else sees 404.
router = APIRouter(
    prefix="/analytics/conversations",
    tags=["conversation"],
    dependencies=[Depends(get_principal)],  # noqa: B008
)

_NOT_FOUND = "Conversation not found."


@router.post(
    "",
    response_model=ConversationResponse,
    dependencies=[Depends(enforce_rate_limit("conversation"))],  # noqa: B008
)
def create_conversation(
    request: Request,
    memory: ConversationMemory = Depends(get_conversation_memory),  # noqa: B008
    principal: Principal = Depends(get_principal),  # noqa: B008
) -> ConversationResponse:
    conversation_id = str(uuid4())
    request.state.conversation_id = conversation_id
    memory.create_session(conversation_id, owner=principal.user_id)
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
    principal: Principal = Depends(get_principal),  # noqa: B008
) -> ConversationResponse:
    request.state.conversation_id = conversation_id
    session = memory.get_session(conversation_id, owner=principal.user_id)
    if session is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
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
        context=memory.build_context(conversation_id, owner=principal.user_id),
    )


@router.post(
    "/{conversation_id}/turns",
    response_model=ConversationTurnResponse,
    dependencies=[Depends(enforce_rate_limit("conversation"))],  # noqa: B008
)
def append_turn(
    request: Request,
    conversation_id: str,
    payload: ConversationTurnRequest,
    memory: ConversationMemory = Depends(get_conversation_memory),  # noqa: B008
    principal: Principal = Depends(get_principal),  # noqa: B008
) -> ConversationTurnResponse:
    request.state.conversation_id = conversation_id
    try:
        turn = memory.add_turn(
            conversation_id, payload.role, payload.content, owner=principal.user_id
        )
    except ConversationAccessError as error:
        raise HTTPException(status_code=404, detail=_NOT_FOUND) from error
    return ConversationTurnResponse(
        conversation_id=conversation_id,
        role=turn.role,
        content=turn.content,
    )
