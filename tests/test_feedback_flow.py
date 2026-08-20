import json

from app.models.feedback_submission import FeedbackSubmission
from app.models.session_state import SessionState
from app.models.teacher_profile import TeacherProfile
from app.services.feedback_survey_service import FeedbackSurveyService


PHONE = "+15550009999"


def send(client, body: str):
    return client.post("/webhook/whatsapp", json={"from": PHONE, "body": body})


def create_teacher(db_session):
    teacher = TeacherProfile(
        whatsapp_number=PHONE,
        teacher_name="Anurag",
        default_grade="10",
        default_subject="Mathematics",
        school_name="Parivaar School",
        preferred_language="English",
    )
    db_session.add(teacher)
    db_session.commit()
    db_session.refresh(teacher)
    return teacher


def test_feedback_survey_runtime_asset_is_present():
    service = FeedbackSurveyService()
    assert service.survey_path.is_file(), (
        "Feedback survey runtime asset is missing. "
        "app/data/weekly_lesson_plan_feedback.json must be committed/deployed."
    )


def test_feedback_json_schema_and_question_numbering():
    survey = FeedbackSurveyService().load()
    questions = survey.flattened_questions()

    assert survey.survey_id == "weekly_lesson_plan_feedback"
    assert survey.version == 1
    assert survey.choice_answer_format == "Yes / Sometimes / No"
    assert [option.label for option in survey.choice_options] == ["Yes", "Sometimes", "No"]
    assert [question.number for _, question in questions] == [1, 2, 3, 4, 5, 6, 7, 8, 10]
    assert len(questions) == 9


def test_main_menu_uses_list_and_includes_feedback(client, db_session):
    create_teacher(db_session)

    payload = send(client, "hello").json()

    assert payload["current_state"] == "MAIN_MENU"
    assert payload["outbound"]["type"] == "list"
    row_ids = [row["id"] for row in payload["outbound"]["rows"]]
    assert row_ids == [
        "menu_new_lesson",
        "menu_all_lessons",
        "menu_my_profile",
        "menu_feedback",
        "menu_admin",
    ]


def test_feedback_flow_saves_all_answers(client, db_session):
    teacher = create_teacher(db_session)

    payload = send(client, "menu_feedback").json()
    assert payload["current_state"] == "FEEDBACK_QUESTION"
    assert payload["outbound"]["type"] == "buttons"
    assert "1. Did you complete the 20-minute Lesson Plan Review" in payload["outbound"]["body"]
    assert [button["title"] for button in payload["outbound"]["buttons"]] == ["Yes", "Sometimes", "No"]

    # Part A: six Yes / Sometimes / No answers.
    for answer_id in [
        "feedback_answer:yes",
        "feedback_answer:sometimes",
        "feedback_answer:no",
        "feedback_answer:yes",
        "feedback_answer:sometimes",
        "feedback_answer:no",
    ]:
        payload = send(client, answer_id).json()

    # After question 6, Part B begins with question 7.
    assert payload["current_state"] == "FEEDBACK_QUESTION"
    assert payload["outbound"] is None
    assert "7. What was the MOST useful part" in payload["reply"]

    payload = send(client, "The teacher explanation and ready-to-use questions.").json()
    assert "8. What was the BIGGEST problem" in payload["reply"]

    payload = send(client, "Some activities needed materials we did not have.").json()
    assert "10. If you could change ONE thing" in payload["reply"]

    payload = send(client, "Add more resource-limited activity alternatives.").json()
    assert payload["current_state"] == "MAIN_MENU"
    assert "feedback has been saved" in payload["reply"].lower()
    assert payload["outbound"]["type"] == "list"

    submission = db_session.query(FeedbackSubmission).one()
    assert submission.teacher_id == teacher.id
    assert submission.school_name == "Parivaar School"
    assert submission.grade == "10"
    assert submission.subject == "Mathematics"

    stored = json.loads(submission.answers_json)
    assert stored["survey_id"] == "weekly_lesson_plan_feedback"
    assert stored["survey_version"] == 1
    assert [item["question_number"] for item in stored["answers"]] == [1, 2, 3, 4, 5, 6, 7, 8, 10]
    assert [item["answer"] for item in stored["answers"][:6]] == [
        "Yes",
        "Sometimes",
        "No",
        "Yes",
        "Sometimes",
        "No",
    ]
    assert stored["answers"][-1]["answer"] == "Add more resource-limited activity alternatives."

    session = db_session.query(SessionState).filter_by(whatsapp_number=PHONE).one()
    assert session.current_state == "MAIN_MENU"
    assert session.temp_feedback_answers_json is None
    assert session.temp_feedback_question_index is None
    assert session.temp_feedback_survey_key is None


def test_feedback_invalid_choice_repeats_same_question(client, db_session):
    create_teacher(db_session)
    send(client, "menu_feedback")

    payload = send(client, "maybe").json()

    assert payload["current_state"] == "FEEDBACK_QUESTION"
    assert "choose Yes, Sometimes, or No" in payload["reply"]
    assert "1. Did you complete the 20-minute Lesson Plan Review" in payload["outbound"]["body"]
    assert db_session.query(FeedbackSubmission).count() == 0


def test_main_menu_interrupt_cancels_in_progress_feedback(client, db_session):
    create_teacher(db_session)
    send(client, "menu_feedback")
    send(client, "feedback_answer:yes")

    payload = send(client, "menu_main_menu").json()

    assert payload["current_state"] == "MAIN_MENU"
    assert payload["outbound"]["type"] == "list"
    assert db_session.query(FeedbackSubmission).count() == 0

    session = db_session.query(SessionState).filter_by(whatsapp_number=PHONE).one()
    assert session.temp_feedback_answers_json is None
