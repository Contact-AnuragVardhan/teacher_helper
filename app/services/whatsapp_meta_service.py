from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import get_logger, log_event

logger = get_logger(__name__)


class WhatsAppMetaService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send_text_message(self, *, to_number: str, body: str) -> dict[str, Any]:
        if not self.settings.whatsapp_access_token:
            raise ValueError("WHATSAPP_ACCESS_TOKEN is not configured.")
        if not self.settings.whatsapp_phone_number_id:
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID is not configured.")

        url = (
            f"https://graph.facebook.com/{self.settings.whatsapp_graph_version}/"
            f"{self.settings.whatsapp_phone_number_id}/messages"
        )
        headers = {
            "Authorization": f"Bearer {self.settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }

        log_event(logger, "whatsapp_graph_send_attempt", to=to_number)
        response = httpx.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.settings.whatsapp_api_timeout_seconds,
        )
        response.raise_for_status()
        result = response.json()
        log_event(logger, "whatsapp_graph_send_success", to=to_number)
        return result