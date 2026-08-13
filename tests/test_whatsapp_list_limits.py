from unittest.mock import Mock, patch

from app.core.config import Settings
from app.services.whatsapp_meta_service import WhatsAppMetaService


@patch("app.services.whatsapp_meta_service.httpx.post")
def test_send_list_message_clamps_meta_field_limits(mock_post):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"messages": [{"id": "wamid.test"}]}
    mock_post.return_value = response

    settings = Settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
    )
    service = WhatsAppMetaService(settings)
    service.send_list_message(
        to_number="15550001111",
        header_text="H" * 100,
        body="B" * 1200,
        button_text="BUTTON" * 10,
        section_title="SECTION" * 10,
        footer_text="F" * 100,
        rows=[
            {"id": "id" * 150, "title": "T" * 50, "description": "D" * 100}
            for _ in range(12)
        ],
    )

    payload = mock_post.call_args.kwargs["json"]
    interactive = payload["interactive"]
    section = interactive["action"]["sections"][0]
    assert len(interactive["header"]["text"]) <= 60
    assert len(interactive["body"]["text"]) <= 1024
    assert len(interactive["action"]["button"]) <= 20
    assert len(interactive["footer"]["text"]) <= 60
    assert len(section["title"]) <= 24
    assert len(section["rows"]) <= 10
    for row in section["rows"]:
        assert len(row["id"]) <= 200
        assert len(row["title"]) <= 24
        assert len(row.get("description", "")) <= 72
