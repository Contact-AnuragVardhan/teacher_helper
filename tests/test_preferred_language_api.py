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


def test_teacher_api_upsert_saves_requested_language_and_updates_hotline(client, db_session, monkeypatch):
    from app.services import preferred_language_api_service

    monkeypatch.setenv("JALTA_SITARA_HOTLINE_LANGUAGE_API_ENABLED", "true")
    get_settings.cache_clear()

    mock_get = Mock(return_value=_mock_language_response("Hindi"))
    mock_post = Mock(return_value=_mock_language_response("English"))
    mock_put = Mock(return_value=_mock_language_response("English"))
    monkeypatch.setattr(preferred_language_api_service.httpx, "get", mock_get)
    monkeypatch.setattr(preferred_language_api_service.httpx, "post", mock_post)
    monkeypatch.setattr(preferred_language_api_service.httpx, "put", mock_put)

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
    assert response.json()["preferred_language"] == "English"

    teacher = db_session.query(TeacherProfile).first()
    assert teacher.preferred_language == "English"

    mock_get.assert_called()
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["json"] == {
        "phone_number": "+15550001111",
        "preferred_language": "English",
    }
    mock_put.assert_not_called()


def test_teacher_api_upsert_does_not_update_hotline_when_language_same(client, db_session, monkeypatch):
    from app.services import preferred_language_api_service

    monkeypatch.setenv("JALTA_SITARA_HOTLINE_LANGUAGE_API_ENABLED", "true")
    get_settings.cache_clear()

    mock_get = Mock(return_value=_mock_language_response("English"))
    mock_post = Mock(return_value=_mock_language_response("English"))
    monkeypatch.setattr(preferred_language_api_service.httpx, "get", mock_get)
    monkeypatch.setattr(preferred_language_api_service.httpx, "post", mock_post)

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
    assert response.json()["preferred_language"] == "English"
    mock_get.assert_called()
    mock_post.assert_not_called()


def test_teacher_api_upsert_continues_when_hotline_fails(client, db_session, monkeypatch):
    from app.services import preferred_language_api_service

    monkeypatch.setenv("JALTA_SITARA_HOTLINE_LANGUAGE_API_ENABLED", "true")
    get_settings.cache_clear()

    def fail(*args, **kwargs):
        raise RuntimeError("hotline unavailable")

    monkeypatch.setattr(preferred_language_api_service.httpx, "get", fail)
    monkeypatch.setattr(preferred_language_api_service.httpx, "post", fail)
    monkeypatch.setattr(preferred_language_api_service.httpx, "put", fail)

    response = client.post(
        "/teacher",
        json={
            "whatsapp_number": "+15550001111",
            "teacher_name": "Anurag",
            "default_grade": "5",
            "default_subject": "English",
            "preferred_language": "Hindi",
        },
    )

    assert response.status_code == 200
    assert response.json()["preferred_language"] == "Hindi"

    teacher = db_session.query(TeacherProfile).first()
    assert teacher.preferred_language == "Hindi"


def test_sync_accepts_old_whatsapp_number_alias_and_posts_only_phone_number(monkeypatch):
    from app.services import preferred_language_api_service
    from app.services.preferred_language_api_service import PreferredLanguageApiService

    monkeypatch.setenv("JALTA_SITARA_HOTLINE_LANGUAGE_API_ENABLED", "true")
    get_settings.cache_clear()

    mock_get = Mock(return_value=_mock_language_response("English"))
    mock_post = Mock(return_value=_mock_language_response("Hindi"))
    monkeypatch.setattr(preferred_language_api_service.httpx, "get", mock_get)
    monkeypatch.setattr(preferred_language_api_service.httpx, "post", mock_post)

    result = PreferredLanguageApiService(get_settings()).sync_preferred_language_if_needed(
        whatsapp_number="+1 (555) 000-1111",
        preferred_language="Hindi",
    )

    assert result is not None
    assert result.preferred_language == "Hindi"
    assert mock_post.call_args.kwargs["json"] == {
        "phone_number": "+15550001111",
        "preferred_language": "Hindi",
    }
    assert "whatsapp_number" not in mock_post.call_args.kwargs["json"]
