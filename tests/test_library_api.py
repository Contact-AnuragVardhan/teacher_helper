from app.models.lesson_plan import LessonPlan


def create_teacher(client):
    response = client.post(
        "/teacher",
        json={
            "whatsapp_number": "+15556667777",
            "teacher_name": "Anurag",
            "default_grade": "5",
            "default_subject": "English",
            "preferred_language": "English",
        },
    )
    assert response.status_code == 200
    teacher = response.json()
    return teacher


def save_library_lesson(client, teacher_id: int, lesson_name: str = "Components of Food Intro"):
    payload = {
        "teacher_id": f"teacher-{teacher_id:03d}",
        "lesson_name": lesson_name,
        "grade": "6",
        "subject": "Science",
        "topic": "Components of Food",
        "duration_minutes": 40,
        "source_type": "ncert_syllabus",
        "source_reference": {
            "grade": "6",
            "subject": "Science",
            "topic_name": "Components of Food",
        },
        "lesson_json": {
            "lesson_title": "Grade 6 Science – Components of Food",
            "objective": "Students understand major nutrients and balanced diet.",
            "opening": "Ask students what they ate today.",
            "main_teaching": "Explain nutrients, balanced diet, and deficiency diseases.",
            "activity": "Students sort foods into nutrient groups.",
            "qa": [
                "What is a balanced diet?",
                "Why do we need nutrients?",
                "Name one deficiency disease.",
            ],
            "closing": "Summarize healthy food choices.",
        },
    }
    response = client.post("/api/library/lessons", json=payload)
    assert response.status_code == 200
    return response


def test_post_api_library_lessons_saves_lesson(client, db_session):
    teacher = create_teacher(client)

    response = save_library_lesson(client, teacher["id"])
    body = response.json()

    assert body["success"] is True
    assert "lesson_id" in body
    assert str(body["lesson_id"]).isdigit()

    lesson = db_session.query(LessonPlan).filter(LessonPlan.id == int(body["lesson_id"])).first()
    assert lesson is not None
    assert lesson.lesson_name == "Components of Food Intro"
    assert lesson.topic == "Components of Food"
    assert lesson.grade == "6"
    assert lesson.subject == "Science"
    assert lesson.duration_minutes == 40


def test_get_api_library_lessons_by_id_returns_saved_lesson(client):
    teacher = create_teacher(client)
    save_response = save_library_lesson(client, teacher["id"])
    lesson_id = save_response.json()["lesson_id"]

    response = client.get(f"/api/library/lessons/{lesson_id}")
    assert response.status_code == 200

    body = response.json()
    assert body["lesson_id"] == str(lesson_id)
    assert body["teacher_id"] == f"teacher-{teacher['id']:03d}"
    assert body["lesson_name"] == "Components of Food Intro"
    assert body["grade"] == "6"
    assert body["subject"] == "Science"
    assert body["topic"] == "Components of Food"
    assert body["duration_minutes"] == 40
    assert body["source_type"] == "ncert_syllabus"
    assert body["source_reference"]["topic_name"] == "Components of Food"
    assert body["lesson_json"]["lesson_title"] == "Grade 6 Science – Components of Food"
    assert body["lesson_json"]["closing"] == "Summarize healthy food choices."


def test_get_api_library_search_returns_filtered_results(client):
    teacher = create_teacher(client)
    save_library_lesson(client, teacher["id"], lesson_name="Components of Food Intro")

    second_payload = {
        "teacher_id": f"teacher-{teacher['id']:03d}",
        "lesson_name": "Plant Life Intro",
        "grade": "6",
        "subject": "Science",
        "topic": "Plant Life",
        "duration_minutes": 35,
        "source_type": "generated",
        "source_reference": {
            "grade": "6",
            "subject": "Science",
            "topic_name": "Plant Life",
        },
        "lesson_json": {
            "lesson_title": "Grade 6 Science – Plant Life",
            "objective": "Students understand basic plant parts.",
            "opening": "Ask students to name a plant.",
            "main_teaching": "Explain roots, stem, leaf, and flower.",
            "activity": "Label plant parts.",
            "qa": ["What do roots do?"],
            "closing": "Summarize plant parts.",
        },
    }

    second_response = client.post("/api/library/lessons", json=second_payload)
    assert second_response.status_code == 200

    response = client.get(
        "/api/library/search",
        params={
            "teacher_id": f"teacher-{teacher['id']:03d}",
            "lesson_name": "Components of Food Intro",
            "grade": "6",
            "subject": "Science",
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["count"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["lesson_name"] == "Components of Food Intro"
    assert body["items"][0]["topic"] == "Components of Food"
    assert body["items"][0]["grade"] == "6"
    assert body["items"][0]["subject"] == "Science"


def test_put_api_library_lessons_updates_lesson_name_and_json(client):
    teacher = create_teacher(client)
    save_response = save_library_lesson(client, teacher["id"])
    lesson_id = save_response.json()["lesson_id"]

    update_payload = {
        "lesson_name": "Components of Food Updated",
        "source_type": "ncert_syllabus",
        "source_reference": {
            "grade": "6",
            "subject": "Science",
            "topic_name": "Components of Food",
        },
        "lesson_json": {
            "lesson_title": "Grade 6 Science – Components of Food Updated",
            "objective": "Students identify nutrients and healthy meals.",
            "opening": "Ask what healthy foods students ate this week.",
            "main_teaching": "Explain nutrients, balance, and food choices.",
            "activity": "Group foods by nutrients.",
            "qa": [
                "What is protein?",
                "What is a balanced diet?",
            ],
            "closing": "Students share one healthy food habit.",
        },
    }

    update_response = client.put(f"/api/library/lessons/{lesson_id}", json=update_payload)
    assert update_response.status_code == 200
    assert update_response.json()["success"] is True
    assert update_response.json()["lesson_id"] == str(lesson_id)

    get_response = client.get(f"/api/library/lessons/{lesson_id}")
    assert get_response.status_code == 200

    body = get_response.json()
    assert body["lesson_name"] == "Components of Food Updated"
    assert body["lesson_json"]["lesson_title"] == "Grade 6 Science – Components of Food Updated"
    assert body["lesson_json"]["objective"] == "Students identify nutrients and healthy meals."
    assert body["lesson_json"]["qa"] == [
        "What is protein?",
        "What is a balanced diet?",
    ]


def test_get_api_library_lessons_by_id_returns_404_for_missing_lesson(client):
    create_teacher(client)

    response = client.get("/api/library/lessons/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Lesson not found."