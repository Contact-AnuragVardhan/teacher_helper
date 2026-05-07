from datetime import datetime, timedelta

from app.models.lesson_plan import LessonPlan
from app.models.teacher_profile import TeacherProfile
from app.repositories.lesson_repository import LessonRepository
from app.services.conversation_service import ConversationService


def test_accessible_lessons_are_sorted_by_lesson_plan_updated_at_desc(db_session):
    teacher = TeacherProfile(
        whatsapp_number="15550009991",
        teacher_name="Teacher One",
        default_grade="5",
        default_subject="Science",
        preferred_language="English",
    )
    db_session.add(teacher)
    db_session.flush()

    older = LessonPlan(
        teacher_id=teacher.id,
        lesson_name="A Alphabetically First",
        topic="Old Topic",
        grade="5",
        subject="Science",
        duration_minutes=30,
        lesson_text="Old lesson",
        updated_at=datetime.utcnow() - timedelta(days=2),
    )
    newer = LessonPlan(
        teacher_id=teacher.id,
        lesson_name="Z Alphabetically Last",
        topic="New Topic",
        grade="5",
        subject="Science",
        duration_minutes=30,
        lesson_text="New lesson",
        updated_at=datetime.utcnow(),
    )
    db_session.add_all([older, newer])
    db_session.commit()

    summaries = LessonRepository(db_session).list_accessible_summaries_for_teacher(teacher.id)

    assert [item.lesson_name for item in summaries] == [
        "Z Alphabetically Last",
        "A Alphabetically First",
    ]


def test_localizing_lesson_titles_preserves_updated_at_desc_order(db_session):
    service = ConversationService(db_session)
    old_time = datetime.utcnow() - timedelta(days=2)
    new_time = datetime.utcnow()
    from app.repositories.lesson_repository import AccessibleLessonSummary

    localized = service._localize_lesson_summaries(
        [
            AccessibleLessonSummary(
                lesson_id=1,
                lesson_name="Z Newer Lesson",
                display_title="Z Newer Lesson",
                is_shared=False,
                topic="New Topic",
                updated_at=new_time,
            ),
            AccessibleLessonSummary(
                lesson_id=2,
                lesson_name="A Older Lesson",
                display_title="A Older Lesson",
                is_shared=False,
                topic="Old Topic",
                updated_at=old_time,
            ),
        ],
        "English",
    )

    assert [item.lesson_name for item in localized] == ["Z Newer Lesson", "A Older Lesson"]
