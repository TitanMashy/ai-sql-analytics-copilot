from fastapi import APIRouter, Depends, Request

from app.core.audit import AuditEvent, get_audit_service
from app.core.auth import Principal, get_principal
from app.core.metrics import metrics
from app.core.rate_limit import enforce_rate_limit
from app.schemas.feedback import FeedbackRequest, FeedbackResponse

router = APIRouter(
    prefix="/analytics",
    tags=["feedback"],
    dependencies=[Depends(get_principal)],  # noqa: B008
)


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    dependencies=[Depends(enforce_rate_limit("conversation"))],  # noqa: B008
    summary="Rate an answer",
    description=(
        "Record whether an answer was helpful. The rating is written to the audit trail with the "
        "request id and the caller's identity; no question or SQL text is stored."
    ),
)
def submit_feedback(
    request: Request,
    payload: FeedbackRequest,
    principal: Principal = Depends(get_principal),  # noqa: B008
) -> FeedbackResponse:
    get_audit_service().record(
        AuditEvent(
            event="feedback",
            outcome="helpful" if payload.helpful else "not_helpful",
            request_id=payload.request_id,
            principal=principal.user_id,
            customer_id=principal.customer_id,
            conversation_id=payload.conversation_id,
            helpful=payload.helpful,
        )
    )
    metrics.record_feedback(payload.helpful)
    request.state.conversation_id = payload.conversation_id
    return FeedbackResponse()
