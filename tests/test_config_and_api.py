from app.core.config import Settings


def test_postgresql_config_loads_correctly():
    settings = Settings(
        DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/teacher_helper",
        LLM_PROVIDER="openai",
        OPENAI_API_KEY="test-key",
        DUPLICATE_LESSON_POLICY="overwrite",
        SESSION_TIMEOUT_MINUTES=45,
    )

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.llm_provider == "openai"
    assert settings.duplicate_lesson_policy == "overwrite"
    assert settings.session_timeout_minutes == 45


def test_lesson_generate_api_shape_stays_compatible(client, db_session):
    client.post(
        "/teacher",
        json={
            "whatsapp_number": "+15559990000",
            "teacher_name": "Teacher",
            "default_grade": "5",
            "default_subject": "Science",
            "preferred_language": "English",
        },
    )

    response = client.post(
        "/lesson/generate",
        json={
            "whatsapp_number": "+15559990000",
            "topic": "Plants",
            "duration_minutes": 35,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "lesson_text" in payload
    assert "Lesson Title" in payload["lesson_text"]
