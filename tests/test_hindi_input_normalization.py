from app.models.teacher_profile import TeacherProfile
from app.utils.subject_normalization import normalize_subject
from app.utils.text import normalize_choice, normalize_grade, parse_duration_minutes


def send(client, body: str, phone: str = "+15550009999"):
    return client.post("/webhook/whatsapp", json={"from": phone, "body": body})


def test_hindi_input_helpers_normalize_subject_grade_duration_and_yes_no():
    assert normalize_subject("गणित") == "Mathematics"
    assert normalize_subject("सामाजिक विज्ञान") == "Social Science"
    assert normalize_grade("कक्षा 6") == "6"
    assert normalize_grade("कक्षा ६") == "6"
    assert parse_duration_minutes("45 मिनट") == 45
    assert parse_duration_minutes("४५ मिनट") == 45
    assert normalize_choice("हाँ") == "yes"
    assert normalize_choice("नहीं") == "no"


def test_profile_creation_accepts_hindi_grade_and_subject(client, db_session):
    send(client, "3")
    send(client, "Anurag")
    send(client, "कक्षा 6")
    send(client, "गणित")
    response = send(client, "Hindi")

    assert response.json()["current_state"] == "MAIN_MENU"

    teacher = db_session.query(TeacherProfile).first()
    assert teacher.default_grade == "6"
    assert teacher.default_subject == "Mathematics"
    assert teacher.preferred_language == "Hindi"


def test_lesson_flow_accepts_hindi_grade_subject_duration_and_yes_save(client, db_session):
    send(client, "3")
    send(client, "Anurag")
    send(client, "6")
    send(client, "Science")
    send(client, "Hindi")

    send(client, "1")
    send(client, "पौधे")
    send(client, "कक्षा 6")
    send(client, "विज्ञान")
    response = send(client, "45 मिनट")
    assert response.json()["current_state"] == "NEW_LESSON_CONFIRM_SAVE"

    response = send(client, "हाँ")
    assert response.json()["current_state"] == "NEW_LESSON_NAME"
