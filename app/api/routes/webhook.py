from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_event
from app.db.session import get_db
from app.schemas.webhook import WhatsAppWebhookRequest, WhatsAppWebhookResponse
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = get_logger(__name__)


@router.post("/whatsapp", response_model=WhatsAppWebhookResponse)
def handle_whatsapp_webhook(
    payload: WhatsAppWebhookRequest,
    db: Session = Depends(get_db),
) -> WhatsAppWebhookResponse:
    log_event(logger, "webhook_inbound", from_number=payload.from_number, body=payload.body)
    service = ConversationService(db)
    result = service.handle_message(payload.from_number, payload.body)
    log_event(
        logger,
        "webhook_outbound",
        to=payload.from_number,
        current_state=result.current_state,
    )
    return WhatsAppWebhookResponse(
        to=payload.from_number,
        reply=result.reply,
        current_state=result.current_state,
    )
