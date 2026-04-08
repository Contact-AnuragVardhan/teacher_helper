from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger, log_event
from app.db.session import get_db
from app.schemas.webhook import WhatsAppWebhookRequest, WhatsAppWebhookResponse
from app.services.conversation_service import ConversationService
from app.services.whatsapp_meta_service import WhatsAppMetaService

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = get_logger(__name__)


@router.get("/whatsapp")
def verify_whatsapp_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    settings: Settings = Depends(get_settings),
) -> PlainTextResponse:
    log_event(logger, "whatsapp_webhook_verification_attempt", hub_mode=hub_mode)

    if hub_mode != "subscribe":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid hub.mode.")

    if not settings.whatsapp_verify_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="WHATSAPP_VERIFY_TOKEN is not configured.",
        )

    if hub_verify_token != settings.whatsapp_verify_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid verify token.")

    if hub_challenge is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing hub.challenge.")

    log_event(logger, "whatsapp_webhook_verification_success")
    return PlainTextResponse(content=hub_challenge)


@router.post("/whatsapp")
async def handle_whatsapp_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    payload = await request.json()

    mock_request = _parse_mock_payload(payload)
    if mock_request is not None:
        return _handle_mock_payload(mock_request, db)

    inbound_message = _extract_meta_inbound_message(payload)
    if inbound_message is None:
        log_event(logger, "whatsapp_webhook_ignored_event")
        return JSONResponse(status_code=200, content={"status": "ignored"})

    log_event(
        logger,
        "whatsapp_webhook_inbound_meta",
        from_number=inbound_message["from_number"],
        message_type=inbound_message["message_type"],
    )

    service = ConversationService(db)
    result = service.handle_message(inbound_message["from_number"], inbound_message["body"])

    whatsapp_service = WhatsAppMetaService(settings)
    try:
        whatsapp_service.send_text_message(to_number=inbound_message["from_number"], body=result.reply)
    except ValueError as exc:
        log_event(logger, "whatsapp_graph_send_skipped", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        log_event(logger, "whatsapp_graph_send_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send WhatsApp reply through Meta Graph API.",
        ) from exc

    log_event(
        logger,
        "whatsapp_webhook_outbound_meta",
        to=inbound_message["from_number"],
        current_state=result.current_state,
    )
    return JSONResponse(status_code=200, content={"status": "processed"})


def _handle_mock_payload(payload: WhatsAppWebhookRequest, db: Session) -> JSONResponse:
    log_event(logger, "webhook_inbound_mock", from_number=payload.from_number, body=payload.body)
    service = ConversationService(db)
    result = service.handle_message(payload.from_number, payload.body)
    log_event(
        logger,
        "webhook_outbound_mock",
        to=payload.from_number,
        current_state=result.current_state,
    )
    response = WhatsAppWebhookResponse(
        to=payload.from_number,
        reply=result.reply,
        current_state=result.current_state,
    )
    return JSONResponse(status_code=200, content=response.model_dump())


def _parse_mock_payload(payload: dict[str, Any]) -> WhatsAppWebhookRequest | None:
    if not isinstance(payload, dict):
        return None
    if "from" not in payload:
        return None
    return WhatsAppWebhookRequest.model_validate(payload)


def _extract_meta_inbound_message(payload: dict[str, Any]) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            if not messages:
                continue

            for message in messages:
                message_type = message.get("type")
                from_number = message.get("from")
                if not from_number or not message_type:
                    continue

                body = _extract_message_body(message)
                if body is None:
                    log_event(
                        logger,
                        "whatsapp_webhook_unsupported_message_type",
                        message_type=message_type,
                        from_number=from_number,
                    )
                    continue

                return {
                    "from_number": from_number,
                    "body": body,
                    "message_type": message_type,
                }
    return None


def _extract_message_body(message: dict[str, Any]) -> str | None:
    message_type = message.get("type")

    if message_type == "text":
        return (message.get("text") or {}).get("body", "").strip()

    if message_type == "interactive":
        interactive = message.get("interactive") or {}
        interactive_type = interactive.get("type")
        if interactive_type == "button_reply":
            button_reply = interactive.get("button_reply") or {}
            return (button_reply.get("title") or button_reply.get("id") or "").strip()
        if interactive_type == "list_reply":
            list_reply = interactive.get("list_reply") or {}
            return (list_reply.get("title") or list_reply.get("id") or "").strip()

    if message_type == "button":
        return (message.get("button") or {}).get("text", "").strip()

    return None