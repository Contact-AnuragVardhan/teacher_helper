from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import get_logger, log_event

logger = get_logger(__name__)


class WhatsAppMetaService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
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

        to_number = payload.get("to", "")
        log_event(
            logger,
            "whatsapp_graph_send_attempt",
            to=to_number,
            message_type=payload.get("type"),
        )

        response = httpx.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.settings.whatsapp_api_timeout_seconds,
        )
        response.raise_for_status()
        result = response.json()

        log_event(
            logger,
            "whatsapp_graph_send_success",
            to=to_number,
            message_type=payload.get("type"),
        )
        return result

    def send_text_message(self, *, to_number: str, body: str) -> dict[str, Any]:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        return self._post(payload)

    def send_reply_buttons(
        self,
        *,
        to_number: str,
        body: str,
        buttons: list[dict[str, str]],
        header_text: str | None = None,
        footer_text: str | None = None,
    ) -> dict[str, Any]:
        interactive: dict[str, Any] = {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": button["id"],
                            "title": button["title"],
                        },
                    }
                    for button in buttons
                ]
            },
        }

        if header_text:
            interactive["header"] = {"type": "text", "text": header_text}
        if footer_text:
            interactive["footer"] = {"text": footer_text}

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "interactive",
            "interactive": interactive,
        }
        return self._post(payload)

    def send_list_message(
        self,
        *,
        to_number: str,
        header_text: str,
        body: str,
        button_text: str,
        rows: list[dict[str, str]],
        footer_text: str | None = None,
        section_title: str = "Options",
    ) -> dict[str, Any]:
        interactive_rows = []
        for row in rows:
            item = {
                "id": row["id"],
                "title": row["title"],
            }
            description = row.get("description")
            if description:
                item["description"] = description
            interactive_rows.append(item)

        interactive: dict[str, Any] = {
            "type": "list",
            "header": {"type": "text", "text": header_text},
            "body": {"text": body},
            "action": {
                "button": button_text,
                "sections": [
                    {
                        "title": section_title,
                        "rows": interactive_rows,
                    }
                ],
            },
        }

        if footer_text:
            interactive["footer"] = {"text": footer_text}

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "interactive",
            "interactive": interactive,
        }
        return self._post(payload)

    def send_outbound_message(
        self,
        *,
        to_number: str,
        reply_text: str,
        outbound: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not outbound or outbound.get("type") == "text":
            return self.send_text_message(to_number=to_number, body=reply_text)

        outbound_type = outbound.get("type")

        if outbound_type == "buttons":
            if reply_text and reply_text.strip():
                self.send_text_message(to_number=to_number, body=reply_text)

            return self.send_reply_buttons(
                to_number=to_number,
                body=outbound["body"],
                buttons=outbound["buttons"],
                header_text=outbound.get("header"),
                footer_text=outbound.get("footer"),
            )

        if outbound_type == "list":
            return self.send_list_message(
                to_number=to_number,
                header_text=outbound["header"],
                body=outbound["body"],
                button_text=outbound["button_text"],
                rows=outbound["rows"],
                footer_text=outbound.get("footer"),
                section_title=outbound.get("section_title", "Options"),
            )

        return self.send_text_message(to_number=to_number, body=reply_text)