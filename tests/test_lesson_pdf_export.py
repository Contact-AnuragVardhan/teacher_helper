import base64
from io import BytesIO

import httpx
from pypdf import PdfReader

from app.core.config import Settings
from app.services.lesson_pdf_service import LessonPdfMetadata, LessonPdfService
from app.services.whatsapp_meta_service import WhatsAppMetaService


def test_lesson_pdf_service_generates_readable_pdf():
    settings = Settings(database_url="sqlite://")
    service = LessonPdfService(settings)

    result = service.generate(
        lesson_text=(
            "LEARNING OBJECTIVES:\n"
            "- Identify the parts of a plant.\n"
            "- Explain why roots are important.\n\n"
            "INTRODUCTION:\n"
            "Ask students what they notice about plants near their home.\n\n"
            "ASSESSMENT:\n"
            "1. Name two functions of roots."
        ),
        metadata=LessonPdfMetadata(
            teacher_name="Ms. Teacher",
            school_name="Sample School",
            grade="5",
            subject="English",
            duration_minutes=35,
            book_title="Sample Book",
            chapter_title="Plants",
            day_title="Day 1",
            pages="2-4",
        ),
    )

    assert result.filename == "Plants_Day_1_Lesson_Plan.pdf"
    assert result.content.startswith(b"%PDF")
    reader = PdfReader(BytesIO(result.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Detailed Lesson Plan" in text
    assert "Ms. Teacher" in text
    assert "LEARNING OBJECTIVES" in text
    assert "Identify the parts of a plant" in text


def test_whatsapp_sequence_uploads_pdf_sends_document_then_buttons(monkeypatch):
    settings = Settings(
        database_url="sqlite://",
        whatsapp_access_token="test-token",
        whatsapp_phone_number_id="123456789",
        whatsapp_graph_version="v23.0",
    )
    service = WhatsAppMetaService(settings)
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        request = httpx.Request("POST", url)
        if url.endswith("/media"):
            return httpx.Response(200, json={"id": "media-123"}, request=request)
        return httpx.Response(200, json={"messages": [{"id": "message-123"}]}, request=request)

    monkeypatch.setattr("app.services.whatsapp_meta_service.httpx.post", fake_post)
    pdf_bytes = b"%PDF-1.4\nexample"
    outbound = {
        "type": "sequence",
        "messages": [
            {
                "type": "document",
                "filename": "lesson.pdf",
                "content_type": "application/pdf",
                "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                "caption": "Teacher Helper - Lesson Plan",
            },
            {
                "type": "buttons",
                "header": "Teacher Helper",
                "body": "Choose an option",
                "footer": "Use, customize, or print",
                "buttons": [
                    {"id": "use_generated_lesson", "title": "Use this lesson"},
                    {"id": "customize_generated_lesson", "title": "Customize Lesson"},
                    {"id": "print_generated_lesson", "title": "Print Lesson"},
                ],
            },
        ],
    }

    result = service.send_outbound_message(
        to_number="15550001111",
        reply_text="Your lesson plan PDF is ready.",
        outbound=outbound,
    )

    assert result["status"] == "sent"
    assert result["message_count"] == 2
    assert len(calls) == 3

    media_url, media_kwargs = calls[0]
    assert media_url.endswith("/media")
    assert media_kwargs["data"] == {"messaging_product": "whatsapp", "type": "application/pdf"}
    assert media_kwargs["files"]["file"][0] == "lesson.pdf"
    assert media_kwargs["files"]["file"][1] == pdf_bytes

    document_url, document_kwargs = calls[1]
    assert document_url.endswith("/messages")
    assert document_kwargs["json"]["type"] == "document"
    assert document_kwargs["json"]["document"]["id"] == "media-123"
    assert document_kwargs["json"]["document"]["filename"] == "lesson.pdf"

    buttons_url, buttons_kwargs = calls[2]
    assert buttons_url.endswith("/messages")
    assert buttons_kwargs["json"]["type"] == "interactive"


def test_mock_webhook_public_outbound_omits_pdf_base64():
    from app.api.routes.webhook import _public_outbound

    public = _public_outbound(
        {
            "type": "sequence",
            "messages": [
                {
                    "type": "document",
                    "filename": "lesson.pdf",
                    "content_base64": "JVBERi0xLjQ=",
                },
                {"type": "buttons", "body": "Options", "buttons": []},
            ],
        }
    )

    document = public["messages"][0]
    assert "content_base64" not in document
    assert document["content_base64_omitted"] is True



def test_pdf_symbol_cleanup_removes_decorative_emoji_and_preserves_math_and_hindi():
    settings = Settings(database_url="sqlite://")
    service = LessonPdfService(settings)

    cleaned = service._strip_unsupported_symbols(
        "📚 ⏱ ⭐ ✅ 👩‍🏫 ax² + bx + c = 0; "
        "a ≠ 0; x ≤ 5; y ≥ 2; √9; ± × ÷; द्विघात समीकरण"
    )

    assert "📚" not in cleaned
    assert "⏱" not in cleaned
    assert "⭐" not in cleaned
    assert "✅" not in cleaned
    assert "👩" not in cleaned
    assert "🏫" not in cleaned

    assert "ax² + bx + c = 0" in cleaned
    assert "a ≠ 0" in cleaned
    assert "x ≤ 5" in cleaned
    assert "y ≥ 2" in cleaned
    assert "√9" in cleaned
    assert "± × ÷" in cleaned
    assert "द्विघात समीकरण" in cleaned


def test_pdf_whatsapp_bold_line_becomes_heading_without_literal_asterisks():
    settings = Settings(database_url="sqlite://")
    service = LessonPdfService(settings)
    styles = service._build_styles("Helvetica", "Helvetica-Bold", False)

    flowables = service._lesson_flowables(
        "*⭐ Teacher Quick View*\nAaj hum concepts ko samjhenge.",
        styles,
    )

    assert flowables[0].style.name == "LessonHeading"
    assert flowables[0].getPlainText() == "Teacher Quick View"
