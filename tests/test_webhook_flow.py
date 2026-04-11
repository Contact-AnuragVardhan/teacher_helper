from datetime import datetime, timedelta

from app.core.messages import DUPLICATE_LESSON_NAME, INVALID_DURATION
from app.models.lesson_plan import LessonPlan
from app.models.session_state import SessionState
from app.models.teacher_profile import TeacherProfile


PHONE = "+15550001111"


def send(client, body: str, phone: str = PHONE):
    return client.post("/webhook/whatsapp", json={"from": phone, "body": body})


def create_profile_via_webhook(client, phone: str = PHONE):
    send(client, "3", phone)
    send(client, "Anurag", phone)
    send(client, "5", phone)
    send(client, "English", phone)
    return send(client, "English", phone)


def generate_lesson_until_save_prompt(
    client,
    phone: str = PHONE,
    topic: str = "Plants",
    grade: str = "5",
    subject: str = "English",
    duration: str = "35",
):
    send(client, "1", phone)
    send(client, topic, phone)
    send(client, grade, phone)
    send(client, subject, phone)
    return send(client, duration, phone)


def save_generated_lesson(client, lesson_name: str, phone: str = PHONE):
    send(client, "1", phone)
    return send(client, lesson_name, phone)


def create_saved_lesson(client, lesson_name: str, topic: str, phone: str = PHONE):
    generate_lesson_until_save_prompt(client, phone=phone, topic=topic)
    save_generated_lesson(client, lesson_name, phone=phone)


def test_successful_profile_creation(client, db_session):
    response = create_profile_via_webhook(client)
    payload = response.json()

    assert payload["current_state"] == "MAIN_MENU"
    assert "1 → New Lesson" in payload["reply"]
    assert "2 → All Lessons" in payload["reply"]

    teacher = db_session.query(TeacherProfile).first()
    assert teacher.default_subject == "English"


def test_successful_lesson_generation_returns_button_outbound(client):
    create_profile_via_webhook(client)
    response = generate_lesson_until_save_prompt(client)
    payload = response.json()

    assert payload["current_state"] == "NEW_LESSON_CONFIRM_SAVE"
    assert payload["outbound"]["type"] == "buttons"


def test_invalid_duration_remains_in_duration_state(client):
    create_profile_via_webhook(client)

    send(client, "1")
    send(client, "Fractions")
    send(client, "5")
    send(client, "English")

    response = send(client, "abc")
    payload = response.json()

    assert payload["current_state"] == "NEW_LESSON_DURATION"
    assert payload["reply"] == INVALID_DURATION


def test_save_lesson_flow_works(client, db_session):
    create_profile_via_webhook(client)

    generate_lesson_until_save_prompt(client)
    send(client, "1")
    send(client, "Plants Basics")

    lesson = db_session.query(LessonPlan).first()
    assert lesson.lesson_name == "Plants Basics"


# =========================
# ALL LESSONS TESTS (FIXED)
# =========================

def test_all_lessons_with_10_or_less_returns_whatsapp_list(client):
    create_profile_via_webhook(client)

    create_saved_lesson(client, "Plants Basics", "Plants")
    create_saved_lesson(client, "Fractions Basics", "Fractions")

    response = send(client, "2")
    payload = response.json()

    assert payload["outbound"]["type"] == "list"

    ids = [row["id"] for row in payload["outbound"]["rows"]]

    assert "Plants Basics" in ids
    assert "Fractions Basics" in ids


def test_all_lessons_with_more_than_10_uses_numbered_fallback(client):
    create_profile_via_webhook(client)

    for i in range(1, 12):
        create_saved_lesson(client, f"Lesson {i}", f"Topic {i}")

    response = send(client, "2")
    payload = response.json()

    assert payload["outbound"] is None
    assert "Reply with the lesson number to open it." in payload["reply"]

    # ✅ no order assumption
    assert "Lesson 1" in payload["reply"]
    assert "Lesson 11" in payload["reply"]


def test_retrieve_existing_lesson_by_number_from_fallback_list_works(client):
    create_profile_via_webhook(client)

    for i in range(1, 12):
        create_saved_lesson(client, f"Lesson {i}", f"Topic {i}")

    send(client, "2")
    response = send(client, "3")

    payload = response.json()

    assert payload["current_state"] == "MAIN_MENU"
    assert "Lesson Title" in payload["reply"]


def test_invalid_lesson_number_keeps_state(client):
    create_profile_via_webhook(client)

    for i in range(1, 12):
        create_saved_lesson(client, f"Lesson {i}", f"Topic {i}")

    send(client, "2")
    response = send(client, "99")

    payload = response.json()

    assert payload["current_state"] == "RETRIEVE_LESSON_NAME"
    assert "Invalid lesson number" in payload["reply"]


def test_all_lessons_exit_to_main_menu(client):
    create_profile_via_webhook(client)

    create_saved_lesson(client, "Plants Basics", "Plants")

    send(client, "2")
    response = send(client, "0")

    payload = response.json()

    assert payload["current_state"] == "MAIN_MENU"