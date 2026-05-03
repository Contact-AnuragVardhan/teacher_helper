from unittest.mock import Mock

from app.core.config import get_settings
from app.models.teacher_profile import TeacherProfile


def _mock_language_response(language: str = "Hindi"):
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "phone_number": "15550001111",
                "preferred_language": language,
                "source": "saved",
                "supported_languages": ["Hindi", "English", "Hinglish"],
            }

    return Response()


def test_teacher_api_upsert_prefers_jalta_sitara_hotline_language(client, db_session, monkeypatch):
    from app.services import preferred_language_api_service

    monkeypatch.setenv("JALTA_SITARA_HOTLINE_LANGUAGE_API_ENABLED", "true")
    get_settings.cache_clear()

    mock_get = Mock(return_value=_mock_language_response("Hindi"))
    monkeypatch.setattr(preferred_language_api_service.httpx, "get", mock_get)

    response = client.post(
        "/teacher",
        json={
            "whatsapp_number": "+15550001111",
            "teacher_name": "Anurag",
            "default_grade": "5",
            "default_subject": "English",
            "preferred_language": "English",
        },
    )

    assert response.status_code == 200
    assert response.json()["preferred_language"] == "Hindi"

    teacher = db_session.query(TeacherProfile).first()
    assert teacher.preferred_language == "Hindi"
