from app.models.lesson_plan import LessonPlan


def create_teacher(
    client,
    phone: str,
    name: str = "Anurag",
    grade: str = "6",
    subject: str = "Science",
    language: str = "English",
):
    response = client.post(
        "/teacher",
        json={
            "whatsapp_number": phone,
            "teacher_name": name,
            "default_grade": grade,
            "default_subject": subject,
            "preferred_language": language,
        },
    )
    assert response.status_code == 200
    return response.json()


def save_library_lesson(
    client,
    teacher_id: int,
    lesson_name: str,
    grade: str = "6",
    subject: str = "Science",
    topic: str = "Components of Food",
    duration_minutes: int = 40,
    source_type: str = "ncert_syllabus",
):
    payload = {
        "teacher_id": f"teacher-{teacher_id:03d}",
        "lesson_name": lesson_name,
        "grade": grade,
        "subject": subject,
        "topic": topic,
        "duration_minutes": duration_minutes,
        "source_type": source_type,
        "source_reference": {
            "grade": grade,
            "subject": subject,
            "topic_name": topic,
        },
        "lesson_json": {
            "lesson_title": f"Grade {grade} {subject} – {topic}",
            "objective": f"Students understand {topic}.",
            "opening": f"Introduce {topic}.",
            "main_teaching": f"Teach {topic}.",
            "activity": f"Practice {topic}.",
            "qa": [
                f"What is {topic}?",
                f"Why is {topic} important?",
            ],
            "closing": f"Summarize {topic}.",
        },
    }
    response = client.post("/api/library/lessons", json=payload)
    assert response.status_code == 200
    return response


def test_post_api_library_lessons_saves_lesson(client, db_session):
    teacher = create_teacher(client, "+15556667771")

    response = save_library_lesson(
        client,
        teacher["id"],
        lesson_name="Components of Food Intro",
        topic="Components of Food",
    )
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
    teacher = create_teacher(client, "+15556667772")
    save_response = save_library_lesson(
        client,
        teacher["id"],
        lesson_name="Components of Food Intro",
        topic="Components of Food",
    )
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
    assert body["lesson_json"]["closing"] == "Summarize Components of Food."


def test_get_api_library_search_without_any_params_returns_all_lessons(client):
    teacher_one = create_teacher(client, "+15556667773", name="Teacher One")
    teacher_two = create_teacher(client, "+15556667774", name="Teacher Two")

    save_library_lesson(
        client,
        teacher_one["id"],
        lesson_name="Components of Food Intro",
        topic="Components of Food",
    )
    save_library_lesson(
        client,
        teacher_one["id"],
        lesson_name="Plant Life Intro",
        topic="Plant Life",
    )
    save_library_lesson(
        client,
        teacher_two["id"],
        lesson_name="Fractions Intro",
        subject="Mathematics",
        topic="Fractions",
        source_type="generated",
    )

    response = client.get("/api/library/search")
    assert response.status_code == 200

    body = response.json()
    assert body["count"] == 3

    lesson_names = {item["lesson_name"] for item in body["items"]}
    assert lesson_names == {
        "Components of Food Intro",
        "Plant Life Intro",
        "Fractions Intro",
    }

    teacher_ids = {item["teacher_id"] for item in body["items"]}
    assert teacher_ids == {
        f"teacher-{teacher_one['id']:03d}",
        f"teacher-{teacher_two['id']:03d}",
    }


def test_get_api_library_search_by_teacher_id_only_returns_that_teachers_lessons(client):
    teacher_one = create_teacher(client, "+15556667775", name="Teacher One")
    teacher_two = create_teacher(client, "+15556667776", name="Teacher Two")

    save_library_lesson(
        client,
        teacher_one["id"],
        lesson_name="Components of Food Intro",
        topic="Components of Food",
    )
    save_library_lesson(
        client,
        teacher_one["id"],
        lesson_name="Plant Life Intro",
        topic="Plant Life",
    )
    save_library_lesson(
        client,
        teacher_two["id"],
        lesson_name="Fractions Intro",
        subject="Mathematics",
        topic="Fractions",
        source_type="generated",
    )

    response = client.get(
        "/api/library/search",
        params={"teacher_id": f"teacher-{teacher_one['id']:03d}"},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["count"] == 2
    assert {item["lesson_name"] for item in body["items"]} == {
        "Components of Food Intro",
        "Plant Life Intro",
    }
    assert {item["teacher_id"] for item in body["items"]} == {
        f"teacher-{teacher_one['id']:03d}",
    }


def test_get_api_library_search_by_topic_only_returns_matching_lessons(client):
    teacher_one = create_teacher(client, "+15556667777", name="Teacher One")
    teacher_two = create_teacher(client, "+15556667778", name="Teacher Two")

    save_library_lesson(
        client,
        teacher_one["id"],
        lesson_name="Components of Food Intro",
        topic="Components of Food",
    )
    save_library_lesson(
        client,
        teacher_one["id"],
        lesson_name="Plant Life Intro",
        topic="Plant Life",
    )
    save_library_lesson(
        client,
        teacher_two["id"],
        lesson_name="Components Deep Dive",
        topic="Components of Food",
        source_type="generated",
    )

    response = client.get(
        "/api/library/search",
        params={"topic": "Components of Food"},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["count"] == 2
    assert {item["lesson_name"] for item in body["items"]} == {
        "Components of Food Intro",
        "Components Deep Dive",
    }
    assert all(item["topic"] == "Components of Food" for item in body["items"])


def test_get_api_library_search_by_grade_and_subject_without_teacher_returns_cross_teacher_matches(client):
    teacher_one = create_teacher(client, "+15556667779", name="Teacher One")
    teacher_two = create_teacher(client, "+15556667780", name="Teacher Two")

    save_library_lesson(
        client,
        teacher_one["id"],
        lesson_name="Components of Food Intro",
        grade="6",
        subject="Science",
        topic="Components of Food",
    )
    save_library_lesson(
        client,
        teacher_two["id"],
        lesson_name="Plant Life Intro",
        grade="6",
        subject="Science",
        topic="Plant Life",
    )
    save_library_lesson(
        client,
        teacher_two["id"],
        lesson_name="Fractions Intro",
        grade="6",
        subject="Mathematics",
        topic="Fractions",
        source_type="generated",
    )

    response = client.get(
        "/api/library/search",
        params={
            "grade": "6",
            "subject": "Science",
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["count"] == 2
    assert {item["lesson_name"] for item in body["items"]} == {
        "Components of Food Intro",
        "Plant Life Intro",
    }
    assert all(item["grade"] == "6" for item in body["items"])
    assert all(item["subject"] == "Science" for item in body["items"])


def test_get_api_library_search_by_teacher_and_topic_returns_single_match(client):
    teacher_one = create_teacher(client, "+15556667781", name="Teacher One")
    teacher_two = create_teacher(client, "+15556667782", name="Teacher Two")

    save_library_lesson(
        client,
        teacher_one["id"],
        lesson_name="Components of Food Intro",
        topic="Components of Food",
    )
    save_library_lesson(
        client,
        teacher_one["id"],
        lesson_name="Plant Life Intro",
        topic="Plant Life",
    )
    save_library_lesson(
        client,
        teacher_two["id"],
        lesson_name="Components Deep Dive",
        topic="Components of Food",
        source_type="generated",
    )

    response = client.get(
        "/api/library/search",
        params={
            "teacher_id": f"teacher-{teacher_one['id']:03d}",
            "topic": "Plant Life",
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["lesson_name"] == "Plant Life Intro"
    assert body["items"][0]["topic"] == "Plant Life"
    assert body["items"][0]["teacher_id"] == f"teacher-{teacher_one['id']:03d}"


def test_get_api_library_search_by_multiple_filters_returns_single_match(client):
    teacher = create_teacher(client, "+15556667783")

    save_library_lesson(
        client,
        teacher["id"],
        lesson_name="Components of Food Intro",
        grade="6",
        subject="Science",
        topic="Components of Food",
    )
    save_library_lesson(
        client,
        teacher["id"],
        lesson_name="Plant Life Intro",
        grade="6",
        subject="Science",
        topic="Plant Life",
    )

    response = client.get(
        "/api/library/search",
        params={
            "teacher_id": f"teacher-{teacher['id']:03d}",
            "lesson_name": "Components of Food Intro",
            "grade": "6",
            "subject": "Science",
            "topic": "Components of Food",
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
    teacher = create_teacher(client, "+15556667784")
    save_response = save_library_lesson(
        client,
        teacher["id"],
        lesson_name="Components of Food Intro",
        topic="Components of Food",
    )
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
    create_teacher(client, "+15556667785")

    response = client.get("/api/library/lessons/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Lesson not found."