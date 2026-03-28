from app.core.messages import (
    DUPLICATE_LESSON_NAME,
    INVALID_DURATION,
    LESSON_NOT_FOUND,
    MAIN_MENU,
)
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
    send(client, "Science", phone)
    return send(client, "English", phone)


def generate_lesson_until_save_prompt(client, phone: str = PHONE):
    send(client, "1", phone)
    send(client, "Plants", phone)
    return send(client, "35", phone)


def test_new_user_hitting_my_profile_flow(client, db_session):
    response = send(client, "My Profile")
    payload = response.json()

    assert response.status_code == 200
    assert payload["current_state"] == "PROFILE_NAME"
    assert "What is your name?" in payload["reply"]

    session = db_session.query(SessionState).filter_by(whatsapp_number=PHONE).first()
    assert session is not None
    assert session.current_state == "PROFILE_NAME"


def test_successful_profile_creation(client, db_session):
    response = create_profile_via_webhook(client)
    payload = response.json()

    assert response.status_code == 200
    assert payload["current_state"] == "MAIN_MENU"
    assert "Your profile has been saved." in payload["reply"]
    assert MAIN_MENU in payload["reply"]

    teacher = db_session.query(TeacherProfile).filter_by(whatsapp_number=PHONE).first()
    assert teacher is not None
    assert teacher.teacher_name == "Anurag"
    assert teacher.default_grade == "5"
    assert teacher.default_subject == "Science"
    assert teacher.preferred_language == "English"


def test_new_lesson_without_profile_redirects_correctly(client):
    response = send(client, "1")
    payload = response.json()

    assert response.status_code == 200
    assert payload["current_state"] == "PROFILE_NAME"
    assert "Please complete your profile first." in payload["reply"]


def test_successful_lesson_generation(client):
    create_profile_via_webhook(client)
    response = generate_lesson_until_save_prompt(client)
    payload = response.json()

    assert response.status_code == 200
    assert payload["current_state"] == "NEW_LESSON_CONFIRM_SAVE"
    assert "Lesson Title" in payload["reply"]
    assert "Objective" in payload["reply"]
    assert "Reply:" in payload["reply"]


def test_invalid_duration_remains_in_duration_state(client):
    create_profile_via_webhook(client)
    send(client, "1")
    send(client, "Fractions")
    response = send(client, "abc")
    payload = response.json()

    assert response.status_code == 200
    assert payload["current_state"] == "NEW_LESSON_DURATION"
    assert payload["reply"] == INVALID_DURATION


def test_save_lesson_flow_works(client, db_session):
    create_profile_via_webhook(client)
    generate_lesson_until_save_prompt(client)
    send(client, "1")
    response = send(client, "Plants Basics")
    payload = response.json()

    assert response.status_code == 200
    assert payload["current_state"] == "MAIN_MENU"
    assert "Your lesson has been saved." in payload["reply"]

    lesson = db_session.query(LessonPlan).first()
    assert lesson is not None
    assert lesson.lesson_name == "Plants Basics"
    assert lesson.topic == "Plants"


def test_cancel_save_discards_temp_lesson(client, db_session):
    create_profile_via_webhook(client)
    generate_lesson_until_save_prompt(client)
    response = send(client, "2")
    payload = response.json()

    assert response.status_code == 200
    assert payload["current_state"] == "MAIN_MENU"
    assert "Lesson creation was cancelled." in payload["reply"]
    assert db_session.query(LessonPlan).count() == 0

    session = db_session.query(SessionState).filter_by(whatsapp_number=PHONE).first()
    assert session.current_state == "MAIN_MENU"
    assert session.temp_generated_lesson is None


def test_retrieve_existing_lesson_works(client):
    create_profile_via_webhook(client)
    generate_lesson_until_save_prompt(client)
    send(client, "1")
    send(client, "Plants Basics")

    send(client, "2")
    response = send(client, "Plants Basics")
    payload = response.json()

    assert response.status_code == 200
    assert payload["current_state"] == "MAIN_MENU"
    assert "Lesson Title" in payload["reply"]
    assert MAIN_MENU in payload["reply"]


def test_retrieve_missing_lesson_returns_correct_message(client):
    create_profile_via_webhook(client)
    send(client, "2")
    response = send(client, "Unknown Lesson")
    payload = response.json()

    assert response.status_code == 200
    assert payload["current_state"] == "RETRIEVE_LESSON_NAME"
    assert payload["reply"] == LESSON_NOT_FOUND


def test_duplicate_lesson_name_rejection(client):
    create_profile_via_webhook(client)
    generate_lesson_until_save_prompt(client)
    send(client, "1")
    send(client, "Plants Basics")

    send(client, "1")
    send(client, "Plants")
    send(client, "35")
    send(client, "1")
    response = send(client, "Plants Basics")
    payload = response.json()

    assert response.status_code == 200
    assert payload["current_state"] == "NEW_LESSON_NAME"
    assert payload["reply"] == DUPLICATE_LESSON_NAME


def test_invalid_main_menu_input(client):
    response = send(client, "hello")
    payload = response.json()

    assert response.status_code == 200
    assert payload["current_state"] == "MAIN_MENU"
    assert payload["reply"].startswith("I did not understand that.")
    assert MAIN_MENU in payload["reply"]
