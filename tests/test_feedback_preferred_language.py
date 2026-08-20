from app.models.teacher_profile import TeacherProfile
from app.services.feedback_survey_service import FeedbackSurveyService


def test_feedback_survey_loader_selects_language_assets():
    service = FeedbackSurveyService()

    english = service.load("English")
    hinglish = service.load("Hinglish")
    hindi = service.load("Hindi")

    assert english.flattened_questions()[0][1].text.startswith("Did you complete")
    assert hinglish.flattened_questions()[0][1].text.startswith("Kya aapne")
    assert hindi.flattened_questions()[0][1].text.startswith("क्या आपने")

    assert [o.label for o in english.choice_options] == ["Yes", "Sometimes", "No"]
    assert [o.label for o in hinglish.choice_options] == ["Haan", "Kabhi-kabhi", "Nahi"]
    assert [o.label for o in hindi.choice_options] == ["हाँ", "कभी-कभी", "नहीं"]


def _teacher(db_session, phone: str, language: str):
    teacher = TeacherProfile(
        whatsapp_number=phone,
        teacher_name=f"Teacher {language}",
        default_grade="10",
        default_subject="English",
        school_name="Parivaar School",
        preferred_language=language,
    )
    db_session.add(teacher)
    db_session.commit()
    return teacher


def _send(client, phone: str, body: str):
    return client.post("/webhook/whatsapp", json={"from": phone, "body": body}).json()


def test_feedback_flow_uses_hinglish_profile_language(client, db_session):
    phone = "+15550008881"
    _teacher(db_session, phone, "Hinglish")

    payload = _send(client, phone, "menu_feedback")

    assert payload["current_state"] == "FEEDBACK_QUESTION"
    assert "Kya aapne is hafte" in payload["outbound"]["body"]
    assert [b["title"] for b in payload["outbound"]["buttons"]] == [
        "Haan", "Kabhi-kabhi", "Nahi"
    ]


def test_feedback_flow_uses_hindi_profile_language(client, db_session):
    phone = "+15550008882"
    _teacher(db_session, phone, "Hindi")

    payload = _send(client, phone, "menu_feedback")

    assert payload["current_state"] == "FEEDBACK_QUESTION"
    assert "क्या आपने इस सप्ताह" in payload["outbound"]["body"]
    assert [b["title"] for b in payload["outbound"]["buttons"]] == [
        "हाँ", "कभी-कभी", "नहीं"
    ]
