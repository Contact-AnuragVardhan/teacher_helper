def test_lesson_generate_api_shape_stays_compatible(client, db_session):
    teacher_response = client.post(
        "/teacher",
        json={
            "whatsapp_number": "+15559990000",
            "teacher_name": "Teacher",
            "default_grade": "5",
            "default_subject": "English",
            "preferred_language": "English",
        },
    )
    assert teacher_response.status_code == 200

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