from app.core.messages import DUPLICATE_LESSON_NAME, INVALID_DURATION
from app.models.lesson_plan import LessonPlan
from app.models.teacher_profile import TeacherProfile


PHONE = "+15550001111"


def send(client, body: str, phone: str = PHONE):
    return client.post("/webhook/whatsapp", json={"from": phone, "body": body})


def create_profile_via_webhook(client, phone: str = PHONE, language: str = "English"):
    send(client, "3", phone)
    send(client, "Anurag", phone)
    send(client, "5", phone)
    send(client, "English", phone)
    return send(client, language, phone)


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
    send(client, "no", phone)
    return send(client, lesson_name, phone)


def create_saved_lesson(client, lesson_name: str, topic: str, phone: str = PHONE):
    generate_lesson_until_save_prompt(client, phone=phone, topic=topic)
    save_generated_lesson(client, lesson_name, phone=phone)


def test_successful_profile_creation(client, db_session):
    response = create_profile_via_webhook(client)
    payload = response.json()

    assert payload["current_state"] == "MAIN_MENU"
    assert "Please tap one option below." in payload["reply"]

    teacher = db_session.query(TeacherProfile).first()
    assert teacher.default_subject == "English"


def test_profile_prompts_include_examples(client):
    response = send(client, "3")
    assert response.json()["current_state"] == "PROFILE_NAME"

    response = send(client, "Anurag")
    assert "Example: 1, 2, 3" in response.json()["reply"]

    response = send(client, "5")
    assert "Example: English" in response.json()["reply"]

    response = send(client, "English")
    assert "English, Hinglish, Hindi" in response.json()["reply"]


def test_successful_lesson_generation_returns_button_outbound(client):
    create_profile_via_webhook(client)
    response = generate_lesson_until_save_prompt(client)
    payload = response.json()

    assert payload["current_state"] == "NEW_LESSON_CONFIRM_SAVE"
    assert payload["outbound"]["type"] == "buttons"


def test_new_lesson_prompts_include_examples(client):
    create_profile_via_webhook(client)

    response = send(client, "1")
    assert 'Example: "Jhansi Ki Rani"' in response.json()["reply"]

    response = send(client, "Plants")
    assert "Example: 1, 2, 3" in response.json()["reply"]

    response = send(client, "5")
    assert "Example: English" in response.json()["reply"]


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
    send(client, "no")
    send(client, "Plants Basics")

    lesson = db_session.query(LessonPlan).first()
    assert lesson.lesson_name == "Plants Basics"


def test_save_lesson_can_use_suggested_name(client, db_session):
    create_profile_via_webhook(client)

    generate_lesson_until_save_prompt(client, topic="Jhansi Ki Rani")
    response = send(client, "1")
    payload = response.json()

    assert payload["current_state"] == "NEW_LESSON_CONFIRM_NAME"
    assert "JhansiKiRani_" in payload["reply"]
    assert "Jhansi_Ki_Rani_" not in payload["reply"]
    assert payload["outbound"]["type"] == "buttons"

    response = send(client, "confirm_suggested_lesson_name")
    assert response.json()["current_state"] == "MAIN_MENU"

    lesson = db_session.query(LessonPlan).first()
    assert lesson.lesson_name.startswith("JhansiKiRani_")



def test_save_lesson_suggested_name_uses_devanagari_for_hindi(client, db_session):
    create_profile_via_webhook(client, language="Hindi")

    generate_lesson_until_save_prompt(client, topic="Jhansi Ki Rani", subject="Social")
    response = send(client, "पाठ सेव करें")
    payload = response.json()

    assert payload["current_state"] == "NEW_LESSON_CONFIRM_NAME"
    assert "झाँसीकीरानी_" in payload["reply"]
    assert "JhansiKiRani_" not in payload["reply"]

    response = send(client, "हाँ")
    assert response.json()["current_state"] == "MAIN_MENU"

    lesson = db_session.query(LessonPlan).first()
    assert lesson.lesson_name.startswith("झाँसीकीरानी_")

def test_profile_can_be_edited_and_saved(client, db_session):
    create_profile_via_webhook(client)

    response = send(client, "3")
    assert "Current profile:" in response.json()["reply"]

    send(client, "same")
    send(client, "6")
    send(client, "same")
    response = send(client, "Hinglish")

    assert response.json()["current_state"] == "MAIN_MENU"

    teacher = db_session.query(TeacherProfile).first()
    assert teacher.teacher_name == "Anurag"
    assert teacher.default_grade == "6"
    assert teacher.default_subject == "English"
    assert teacher.preferred_language == "Hinglish"


def test_hindi_profile_edit_accepts_hindi_same_words(client, db_session):
    create_profile_via_webhook(client, language="Hindi")

    response = send(client, "3")
    assert "वर्तमान प्रोफ़ाइल" in response.json()["reply"]

    send(client, "सेम")
    send(client, "समान")
    send(client, "सेम")
    response = send(client, "समान")

    assert response.json()["current_state"] == "MAIN_MENU"

    teacher = db_session.query(TeacherProfile).first()
    assert teacher.teacher_name == "Anurag"
    assert teacher.default_grade == "5"
    assert teacher.default_subject == "English"
    assert teacher.preferred_language == "Hindi"


def test_hinglish_profile_generates_hinglish_lesson(client):
    create_profile_via_webhook(client, language="Hinglish")

    response = generate_lesson_until_save_prompt(client, topic="Plants")
    payload = response.json()

    assert payload["current_state"] == "NEW_LESSON_CONFIRM_SAVE"
    assert "basic idea samajhna" in payload["reply"]


def test_hindi_profile_generates_devanagari_lesson(client, db_session):
    create_profile_via_webhook(client, language="Hindi")

    response = generate_lesson_until_save_prompt(client, topic="Plants")
    payload = response.json()

    assert payload["current_state"] == "NEW_LESSON_CONFIRM_SAVE"
    assert "पाठ योजना" in payload["reply"]
    assert "उद्देश्य" in payload["reply"]
    assert "मुख्य बात समझना" in payload["reply"]

    teacher = db_session.query(TeacherProfile).first()
    assert teacher.preferred_language == "Hindi"






def test_all_lessons_with_10_or_less_returns_whatsapp_list(client):
    create_profile_via_webhook(client)

    create_saved_lesson(client, "Plants Basics", "Plants")
    create_saved_lesson(client, "Fractions Basics", "Fractions")

    response = send(client, "2")
    payload = response.json()

    assert payload["outbound"]["type"] == "list"

    ids = [row["id"] for row in payload["outbound"]["rows"]]
    titles = [row["title"] for row in payload["outbound"]["rows"]]

    assert any(item.startswith("lesson_id:") for item in ids)
    assert "Plants Basics" in titles
    assert "Fractions Basics" in titles


def test_all_lessons_with_more_than_10_uses_numbered_fallback(client):
    create_profile_via_webhook(client)

    for i in range(1, 12):
        create_saved_lesson(client, f"Lesson {i}", f"Topic {i}")

    response = send(client, "2")
    payload = response.json()

    assert payload["outbound"] is None
    assert "Reply with the lesson number to open it." in payload["reply"]
    assert "Lesson 1" in payload["reply"]
    assert "Lesson 11" in payload["reply"]


def test_retrieve_existing_lesson_by_number_from_fallback_list_works(client):
    create_profile_via_webhook(client)

    for i in range(1, 12):
        create_saved_lesson(client, f"Lesson {i}", f"Topic {i}")

    send(client, "2")
    response = send(client, "3")

    payload = response.json()

    assert payload["current_state"] == "LESSON_ACTION_MENU"
    assert "Lesson Title" in payload["reply"]
    assert payload["outbound"]["type"] == "buttons"


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


def test_duplicate_lesson_name_message_has_example(client):
    create_profile_via_webhook(client)

    create_saved_lesson(client, "Plants Basics", "Plants")
    generate_lesson_until_save_prompt(client, topic="Trees")
    send(client, "1")
    send(client, "no")
    response = send(client, "Plants Basics")

    assert response.json()["reply"] == DUPLICATE_LESSON_NAME



def test_owner_can_share_lesson_and_recipient_sees_starred_entry(client):
    owner_phone = PHONE
    recipient_phone = "+15550002222"

    create_profile_via_webhook(client, phone=owner_phone)
    create_profile_via_webhook(client, phone=recipient_phone)
    create_saved_lesson(client, "Plants Basics", "Plants", phone=owner_phone)

    open_list_response = send(client, "2", owner_phone)
    lesson_row_id = open_list_response.json()["outbound"]["rows"][0]["id"]

    send(client, lesson_row_id, owner_phone)
    share_prompt = send(client, "lesson_action_share", owner_phone)
    assert share_prompt.json()["current_state"] == "SHARE_LESSON_PHONE"

    share_result = send(client, recipient_phone, owner_phone)
    assert share_result.json()["current_state"] == "MAIN_MENU"
    assert "was shared with" in share_result.json()["reply"]

    recipient_list = send(client, "2", recipient_phone).json()
    assert recipient_list["outbound"]["type"] == "list"
    assert any(row["title"].startswith("*") for row in recipient_list["outbound"]["rows"])


def test_owner_can_delete_lesson_from_action_menu(client):
    create_profile_via_webhook(client)
    create_saved_lesson(client, "Plants Basics", "Plants")

    open_list_response = send(client, "2")
    lesson_row_id = open_list_response.json()["outbound"]["rows"][0]["id"]

    send(client, lesson_row_id)
    delete_prompt = send(client, "lesson_action_delete")
    assert delete_prompt.json()["current_state"] == "DELETE_LESSON_CONFIRM"

    delete_result = send(client, "confirm_delete_lesson")
    assert delete_result.json()["current_state"] == "MAIN_MENU"
    assert "was deleted" in delete_result.json()["reply"]

    lessons_after_delete = send(client, "2").json()
    assert "do not have any saved or shared lessons yet" in lessons_after_delete["reply"]


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


def test_profile_creation_saves_language_from_jalta_sitara_hotline_api(client, db_session, monkeypatch):
    from unittest.mock import Mock

    from app.core.config import get_settings
    from app.services import preferred_language_api_service

    monkeypatch.setenv("JALTA_SITARA_HOTLINE_LANGUAGE_API_ENABLED", "true")
    monkeypatch.setenv("JALTA_SITARA_HOTLINE_BASE_URL", "https://student-helper-reai.onrender.com")
    get_settings.cache_clear()

    mock_get = Mock(return_value=_mock_language_response("Hindi"))
    monkeypatch.setattr(preferred_language_api_service.httpx, "get", mock_get)

    send(client, "3")
    send(client, "Anurag")
    send(client, "5")
    response = send(client, "English")

    payload = response.json()
    assert payload["current_state"] == "MAIN_MENU"
    assert "प्रोफ़ाइल सेव हो गई" in payload["reply"]

    teacher = db_session.query(TeacherProfile).first()
    assert teacher.preferred_language == "Hindi"
    assert teacher.default_subject == "English"


def test_existing_profile_language_syncs_from_jalta_sitara_hotline_api(client, db_session, monkeypatch):
    from unittest.mock import Mock

    from app.core.config import get_settings
    from app.services import preferred_language_api_service

    create_profile_via_webhook(client, language="English")
    teacher = db_session.query(TeacherProfile).first()
    assert teacher.preferred_language == "English"

    monkeypatch.setenv("JALTA_SITARA_HOTLINE_LANGUAGE_API_ENABLED", "true")
    get_settings.cache_clear()

    mock_get = Mock(return_value=_mock_language_response("Hindi"))
    monkeypatch.setattr(preferred_language_api_service.httpx, "get", mock_get)

    response = send(client, "hello")
    assert response.json()["current_state"] == "MAIN_MENU"

    db_session.refresh(teacher)
    assert teacher.preferred_language == "Hindi"
