from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.webhook import WhatsAppWebhookRequest, WhatsAppWebhookResponse
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post("/whatsapp", response_model=WhatsAppWebhookResponse)
def handle_whatsapp_webhook(
    payload: WhatsAppWebhookRequest,
    db: Session = Depends(get_db),
) -> WhatsAppWebhookResponse:
    service = ConversationService(db)
    result = service.handle_message(payload.from_number, payload.body)
    return WhatsAppWebhookResponse(
        to=payload.from_number,
        reply=result.reply,
        current_state=result.current_state,
    )
