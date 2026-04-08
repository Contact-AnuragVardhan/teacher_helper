from unittest.mock import Mock, patch

from app.core.config import get_settings


VERIFY_TOKEN = "test-verify-token"
PHONE = "15550001111"


def test_whatsapp_webhook_verification_success(client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", VERIFY_TOKEN)
    get_settings.cache_clear()

    response = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "12345",
        },
    )

    assert response.status_code == 200
    assert response.text == "12345"


def test_whatsapp_webhook_verification_invalid_token(client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", VERIFY_TOKEN)
    get_settings.cache_clear()

    response = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "12345",
        },
    )

    assert response.status_code == 403


@patch("app.services.whatsapp_meta_service.httpx.post")
def test_meta_text_message_is_processed_and_replied(mock_post, client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", VERIFY_TOKEN)
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456789")
    get_settings.cache_clear()

    mock_response = Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"messages": [{"id": "wamid.123"}]}
    mock_post.return_value = mock_response

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": PHONE,
                                    "type": "text",
                                    "text": {"body": "My Profile"},
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }

    response = client.post("/webhook/whatsapp", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "processed"}

    args, kwargs = mock_post.call_args
    assert "123456789/messages" in args[0]
    assert kwargs["headers"]["Authorization"] == "Bearer access-token"
    assert kwargs["json"]["to"] == PHONE
    assert "What is your name?" in kwargs["json"]["text"]["body"]


@patch("app.services.whatsapp_meta_service.httpx.post")
def test_meta_status_event_is_ignored(mock_post, client):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "id": "wamid.123",
                                    "status": "delivered",
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }

    response = client.post("/webhook/whatsapp", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    mock_post.assert_not_called()