import json
from datetime import datetime, time, timedelta

from app.core.config import get_settings
from app.models.feedback_submission import FeedbackSubmission
from app.models.teacher_profile import TeacherProfile
from app.repositories.admin_repository import AdminRepository


ADMIN_PHONE = "+15550007777"
TEACHER_PHONE = "+15550008888"


def send(client, body: str):
    return client.post("/webhook/whatsapp", json={"from": ADMIN_PHONE, "body": body})


def create_teacher(db_session):
    teacher = TeacherProfile(
        whatsapp_number=TEACHER_PHONE,
        teacher_name="Teacher Asha",
        default_grade="10",
        default_subject="Mathematics",
        school_name="Parivaar School",
        preferred_language="English",
    )
    db_session.add(teacher)
    db_session.commit()
    db_session.refresh(teacher)
    return teacher


def test_admin_login_usage_feedback_and_exit(client, db_session, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "9876")
    monkeypatch.setenv("ADMIN_TEACHERS", TEACHER_PHONE)
    monkeypatch.setenv("ADMIN_REPORT_TIMEZONE", "UTC")
    get_settings.cache_clear()

    teacher = create_teacher(db_session)

    payload = send(client, "menu_admin").json()
    assert payload["current_state"] == "ADMIN_PASSWORD"
    assert "4-digit password" in payload["reply"]

    payload = send(client, "1111").json()
    assert payload["current_state"] == "ADMIN_PASSWORD"
    assert "Incorrect ADMIN password" in payload["reply"]

    payload = send(client, "9876").json()
    assert payload["current_state"] == "ADMIN_MENU"
    assert [row["id"] for row in payload["outbound"]["rows"]] == [
        "admin_usage",
        "admin_feedback",
        "admin_exit",
    ]

    payload = send(client, "admin_usage").json()
    assert payload["current_state"] == "ADMIN_SELECT_TEACHER"
    teacher_row = next(row for row in payload["outbound"]["rows"] if row["id"] == f"admin_teacher:{teacher.id}")
    assert teacher_row["title"] == "Teacher Asha"

    payload = send(client, f"admin_teacher:{teacher.id}").json()
    assert payload["current_state"] == "ADMIN_SELECT_WEEK"
    week_rows = [row for row in payload["outbound"]["rows"] if row["id"].startswith("admin_week:")]
    assert len(week_rows) == 4

    week_start = datetime.fromisoformat(week_rows[0]["id"].split(":", 1)[1]).date()
    admin_repo = AdminRepository(db_session)
    sunday_10 = datetime.combine(week_start, time(10, 0))
    admin_repo.record_teacher_activity(teacher=teacher, whatsapp_number=TEACHER_PHONE, occurred_at=sunday_10)
    admin_repo.record_teacher_activity(
        teacher=teacher,
        whatsapp_number=TEACHER_PHONE,
        occurred_at=sunday_10 + timedelta(minutes=10),
    )
    admin_repo.record_teacher_activity(
        teacher=teacher,
        whatsapp_number=TEACHER_PHONE,
        occurred_at=sunday_10 + timedelta(hours=1),
    )
    admin_repo.record_teacher_activity(
        teacher=teacher,
        whatsapp_number=TEACHER_PHONE,
        occurred_at=sunday_10 + timedelta(days=1),
    )

    payload = send(client, week_rows[0]["id"]).json()
    assert payload["current_state"] == "ADMIN_MENU"
    assert "Teacher Usage: Teacher Asha" in payload["reply"]
    assert f"Sunday {week_start.strftime('%b %d')}: 11 minutes" in payload["reply"]
    monday = week_start + timedelta(days=1)
    assert f"Monday {monday.strftime('%b %d')}: 1 minute" in payload["reply"]
    assert len([line for line in payload["reply"].splitlines() if ":" in line and "minute" in line]) == 7

    feedback_payload = {
        "survey_id": "weekly_lesson_plan_feedback",
        "survey_version": 1,
        "answers": [
            {"question": "Question that must not appear", "answer": "Very useful lesson plan."},
            {"question": "Another hidden question", "answer": "Need shorter activities."},
        ],
    }
    db_session.add(
        FeedbackSubmission(
            teacher_id=teacher.id,
            whatsapp_number=TEACHER_PHONE,
            survey_id="weekly_lesson_plan_feedback",
            survey_version=1,
            teacher_name=teacher.teacher_name,
            school_name=teacher.school_name,
            grade=teacher.default_grade,
            subject=teacher.default_subject,
            preferred_language=teacher.preferred_language,
            answers_json=json.dumps(feedback_payload),
            submitted_at=datetime.combine(week_start + timedelta(days=2), time(12, 0)),
        )
    )
    db_session.commit()

    payload = send(client, "admin_feedback").json()
    payload = send(client, f"admin_teacher:{teacher.id}").json()
    week_row = next(row for row in payload["outbound"]["rows"] if row["id"] == f"admin_week:{week_start.isoformat()}")
    payload = send(client, week_row["id"]).json()
    assert payload["current_state"] == "ADMIN_MENU"
    assert "Very useful lesson plan.\nNeed shorter activities." in payload["reply"]
    assert "Question that must not appear" not in payload["reply"]
    assert "Another hidden question" not in payload["reply"]

    payload = send(client, "admin_exit").json()
    assert payload["current_state"] == "MAIN_MENU"
    assert payload["outbound"]["type"] == "list"


def test_main_menu_contains_admin(client):
    payload = send(client, "hello").json()
    row_ids = [row["id"] for row in payload["outbound"]["rows"]]
    assert row_ids[-1] == "menu_admin"


def test_admin_teacher_list_is_restricted_by_env(client, db_session, monkeypatch):
    allowed = create_teacher(db_session)
    hidden = TeacherProfile(
        whatsapp_number="+15550009999",
        teacher_name="Hidden Teacher",
        default_grade="8",
        default_subject="English",
        school_name="Other School",
        preferred_language="English",
    )
    db_session.add(hidden)
    db_session.commit()
    db_session.refresh(hidden)

    monkeypatch.setenv("ADMIN_PASSWORD", "9876")
    monkeypatch.setenv("ADMIN_TEACHERS", TEACHER_PHONE)
    get_settings.cache_clear()

    send(client, "menu_admin")
    send(client, "9876")
    payload = send(client, "admin_usage").json()
    row_ids = [row["id"] for row in payload["outbound"]["rows"]]
    assert f"admin_teacher:{allowed.id}" in row_ids
    assert f"admin_teacher:{hidden.id}" not in row_ids

    # A forged interactive row ID must not bypass the env allowlist.
    payload = send(client, f"admin_teacher:{hidden.id}").json()
    assert payload["current_state"] == "ADMIN_SELECT_TEACHER"
    assert "Hidden Teacher" not in json.dumps(payload)
