from unittest.mock import Mock, patch

from app.core.config import get_settings


VERIFY_TOKEN = "test-verify-token"
PHONE = "15550001111"


@patch("app.services.whatsapp_meta_service.httpx.post")
def test_meta_all_lessons_with_10_or_less_sends_interactive_list(mock_post, client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456789")
    monkeypatch.setenv("SUPPORTED_LANGUAGES", "English,Hinglish")
    get_settings.cache_clear()

    mock_response = Mock()
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    client.post("/webhook/whatsapp", json={"from": PHONE, "body": "3"})
    client.post("/webhook/whatsapp", json={"from": PHONE, "body": "Anurag"})
    client.post("/webhook/whatsapp", json={"from": PHONE, "body": "5"})
    client.post("/webhook/whatsapp", json={"from": PHONE, "body": "English"})
    client.post("/webhook/whatsapp", json={"from": PHONE, "body": "English"})

    for lesson_name in ["Plants Basics", "Fractions Basics"]:
        client.post("/webhook/whatsapp", json={"from": PHONE, "body": "1"})
        client.post("/webhook/whatsapp", json={"from": PHONE, "body": "Topic"})
        client.post("/webhook/whatsapp", json={"from": PHONE, "body": "5"})
        client.post("/webhook/whatsapp", json={"from": PHONE, "body": "English"})
        client.post("/webhook/whatsapp", json={"from": PHONE, "body": "35"})
        client.post("/webhook/whatsapp", json={"from": PHONE, "body": "1"})
        client.post("/webhook/whatsapp", json={"from": PHONE, "body": lesson_name})

    mock_post.reset_mock()

    client.post(
        "/webhook/whatsapp",
        json={
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {"messages": [{"from": PHONE, "type": "text", "text": {"body": "2"}}]}}]}],
        },
    )

    args, kwargs = mock_post.call_args

    rows = kwargs["json"]["interactive"]["action"]["sections"][0]["rows"]

    ids = [row["id"] for row in rows]

    assert "Plants Basics" in ids
    assert "Fractions Basics" in ids
