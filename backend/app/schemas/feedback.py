from __future__ import annotations

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    """A thumbs up/down on one answer.

    There is deliberately no free-text field: feedback is recorded in the audit trail, which holds
    identifiers and counts, never user-written content.
    """

    request_id: str = Field(
        pattern=r"^[A-Za-z0-9._-]{1,64}$",
        description="The request_id returned with the answer being rated.",
    )
    helpful: bool
    conversation_id: str | None = Field(default=None, max_length=128)


class FeedbackResponse(BaseModel):
    status: str = "recorded"


class BusinessDefinitionResponse(BaseModel):
    name: str
    definition: str


class BusinessDefinitionsResponse(BaseModel):
    definitions: list[BusinessDefinitionResponse]
    examples: list[str]
