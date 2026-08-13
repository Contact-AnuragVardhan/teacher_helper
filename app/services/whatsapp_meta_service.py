from __future__ import annotations

import base64
import binascii
from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import get_logger, log_event

logger = get_logger(__name__)


class WhatsAppMetaService:
    MAX_TEXT_MESSAGE_LENGTH = 4000

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

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            response_preview = response.text[:1000] if response.text else ""
            log_event(
                logger,
                "whatsapp_graph_send_http_error",
                to=to_number,
                message_type=payload.get("type"),
                status_code=response.status_code,
                response_preview=response_preview,
            )
            raise

        result = response.json()

        log_event(
            logger,
            "whatsapp_graph_send_success",
            to=to_number,
            message_type=payload.get("type"),
        )
        return result

    def _upload_media(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> str:
        if not self.settings.whatsapp_access_token:
            raise ValueError("WHATSAPP_ACCESS_TOKEN is not configured.")
        if not self.settings.whatsapp_phone_number_id:
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID is not configured.")
        if not content:
            raise ValueError("Document content is empty.")

        url = (
            f"https://graph.facebook.com/{self.settings.whatsapp_graph_version}/"
            f"{self.settings.whatsapp_phone_number_id}/media"
        )
        headers = {"Authorization": f"Bearer {self.settings.whatsapp_access_token}"}
        files = {"file": (filename, content, content_type)}
        data = {"messaging_product": "whatsapp", "type": content_type}

        log_event(
            logger,
            "whatsapp_graph_media_upload_attempt",
            filename=filename,
            content_type=content_type,
            content_length=len(content),
        )
        response = httpx.post(
            url,
            headers=headers,
            data=data,
            files=files,
            timeout=self.settings.whatsapp_api_timeout_seconds,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            response_preview = response.text[:1000] if response.text else ""
            log_event(
                logger,
                "whatsapp_graph_media_upload_http_error",
                filename=filename,
                status_code=response.status_code,
                response_preview=response_preview,
            )
            raise

        result = response.json()
        media_id = str(result.get("id") or "").strip()
        if not media_id:
            raise ValueError("WhatsApp media upload response did not contain a media id.")
        log_event(
            logger,
            "whatsapp_graph_media_upload_success",
            filename=filename,
            media_id=media_id,
        )
        return media_id

    def send_document_message(
        self,
        *,
        to_number: str,
        content: bytes,
        filename: str,
        content_type: str = "application/pdf",
        caption: str | None = None,
    ) -> dict[str, Any]:
        media_id = self._upload_media(
            content=content,
            filename=filename,
            content_type=content_type,
        )
        document: dict[str, Any] = {"id": media_id, "filename": filename}
        if caption and caption.strip():
            document["caption"] = caption.strip()
        return self._post(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to_number,
                "type": "document",
                "document": document,
            }
        )

    @staticmethod
    def _decode_base64_content(value: str) -> bytes:
        try:
            return base64.b64decode(value or "", validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Outbound document content_base64 is invalid.") from exc

    def _normalize_text_body(self, body: str) -> str:
        return (body or "").replace("\r\n", "\n").strip()

    def _split_text_chunks(self, body: str) -> list[str]:
        normalized = self._normalize_text_body(body)
        if not normalized:
            return []

        if len(normalized) <= self.MAX_TEXT_MESSAGE_LENGTH:
            return [normalized]

        chunks: list[str] = []
        remaining = normalized

        while remaining:
            if len(remaining) <= self.MAX_TEXT_MESSAGE_LENGTH:
                chunks.append(remaining.strip())
                break

            split_at = remaining.rfind("\n\n", 0, self.MAX_TEXT_MESSAGE_LENGTH)
            if split_at == -1:
                split_at = remaining.rfind("\n", 0, self.MAX_TEXT_MESSAGE_LENGTH)
            if split_at == -1:
                split_at = remaining.rfind(". ", 0, self.MAX_TEXT_MESSAGE_LENGTH)
                if split_at != -1:
                    split_at += 1
            if split_at == -1:
                split_at = remaining.rfind(" ", 0, self.MAX_TEXT_MESSAGE_LENGTH)
            if split_at == -1:
                split_at = self.MAX_TEXT_MESSAGE_LENGTH

            chunk = remaining[:split_at].strip()
            if not chunk:
                chunk = remaining[: self.MAX_TEXT_MESSAGE_LENGTH].strip()
                split_at = len(chunk)

            chunks.append(chunk)
            remaining = remaining[split_at:].lstrip()

        return [chunk for chunk in chunks if chunk]

    def send_text_message(self, *, to_number: str, body: str) -> dict[str, Any]:
        normalized_body = self._normalize_text_body(body)
        if not normalized_body:
            return {"status": "skipped", "reason": "empty_body"}

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "text",
            "text": {"preview_url": False, "body": normalized_body},
        }
        return self._post(payload)

    def send_text_messages(self, *, to_number: str, body: str) -> dict[str, Any]:
        chunks = self._split_text_chunks(body)
        if not chunks:
            return {"status": "skipped", "reason": "empty_body", "chunk_count": 0}

        last_result: dict[str, Any] = {}
        for index, chunk in enumerate(chunks, start=1):
            log_event(
                logger,
                "whatsapp_graph_send_text_chunk",
                to=to_number,
                chunk_index=index,
                chunk_count=len(chunks),
                chunk_length=len(chunk),
            )
            last_result = self.send_text_message(to_number=to_number, body=chunk)

        return {"status": "sent", "chunk_count": len(chunks), "last_result": last_result}

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
        # Meta WhatsApp interactive-list fields have strict length limits.
        # Enforce them centrally so a slightly long translated label/footer
        # cannot make Graph API reject the list after the plain-text reply was
        # already sent (which can also cause webhook retries/duplicate replies).
        safe_header = (header_text or "")[:60]
        safe_body = (body or "")[:1024]
        safe_button = (button_text or "Options")[:20]
        safe_section = (section_title or "Options")[:24]
        safe_footer = (footer_text or "")[:60]

        interactive_rows = []
        for row in rows[:10]:
            row_id = str(row.get("id") or "")[:200]
            row_title = str(row.get("title") or "")[:24]
            if not row_id or not row_title:
                continue
            item = {
                "id": row_id,
                "title": row_title,
            }
            description = str(row.get("description") or "")[:72]
            if description:
                item["description"] = description
            interactive_rows.append(item)

        if not interactive_rows:
            raise ValueError("WhatsApp list message requires at least one valid row.")

        interactive: dict[str, Any] = {
            "type": "list",
            "header": {"type": "text", "text": safe_header},
            "body": {"text": safe_body},
            "action": {
                "button": safe_button,
                "sections": [
                    {
                        "title": safe_section,
                        "rows": interactive_rows,
                    }
                ],
            },
        }

        if safe_footer:
            interactive["footer"] = {"text": safe_footer}

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "interactive",
            "interactive": interactive,
        }
        return self._post(payload)

    def _send_outbound_item(self, *, to_number: str, item: dict[str, Any]) -> dict[str, Any]:
        item_type = item.get("type")
        if item_type == "text":
            return self.send_text_messages(to_number=to_number, body=item.get("body", ""))
        if item_type == "buttons":
            return self.send_reply_buttons(
                to_number=to_number,
                body=item["body"],
                buttons=item["buttons"],
                header_text=item.get("header"),
                footer_text=item.get("footer"),
            )
        if item_type == "list":
            return self.send_list_message(
                to_number=to_number,
                header_text=item["header"],
                body=item["body"],
                button_text=item["button_text"],
                rows=item["rows"],
                footer_text=item.get("footer"),
                section_title=item.get("section_title", "Options"),
            )
        if item_type == "document":
            content = self._decode_base64_content(item.get("content_base64", ""))
            return self.send_document_message(
                to_number=to_number,
                content=content,
                filename=item.get("filename") or "lesson-plan.pdf",
                content_type=item.get("content_type") or "application/pdf",
                caption=item.get("caption"),
            )
        raise ValueError(f"Unsupported outbound message type: {item_type!r}")

    def send_outbound_message(
        self,
        *,
        to_number: str,
        reply_text: str,
        outbound: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not outbound or outbound.get("type") == "text":
            return self.send_text_messages(to_number=to_number, body=reply_text)

        outbound_type = outbound.get("type")
        if outbound_type == "sequence":
            results = [
                self._send_outbound_item(to_number=to_number, item=item)
                for item in outbound.get("messages", [])
            ]
            return {"status": "sent", "message_count": len(results), "results": results}

        if reply_text and reply_text.strip():
            self.send_text_messages(to_number=to_number, body=reply_text)
        return self._send_outbound_item(to_number=to_number, item=outbound)
