from app.repositories.embedding_content_repository import (
    EmbeddingLessonMatch,
    EmbeddingTeacherSchedule,
    EmbeddingTeacherScheduleDay,
)
from app.services.conversation_service import ConversationService


def _lesson() -> EmbeddingLessonMatch:
    return EmbeddingLessonMatch(
        document_id="doc-1",
        chapter_id="chapter-3",
        document_key="maths",
        school_name="Parivaar School",
        grade="10",
        class_name="Class-10",
        subject="Mathematics",
        book_title="NCERT Maths",
        chapter_number="3",
        chapter_title="दो चर वाले रैखिक समीकरण युग्म",
        unit_number=None,
        unit_title=None,
        section_number="3",
        section_title="दो चर वाले रैखिक समीकरण युग्म",
        lesson_title=None,
        structure_type="chapter",
        pdf_start_page=44,
        pdf_end_page=58,
        printed_start_page="28",
        printed_end_page="42",
        text="chapter text",
    )


def _day(day: int, weekday: str, questions: list[str], pages: list[int]) -> EmbeddingTeacherScheduleDay:
    return EmbeddingTeacherScheduleDay(
        id=f"day-{day}",
        teacher_schedule_id="schedule-1",
        document_id="doc-1",
        day=day,
        weekday=weekday,
        day_type="instruction",
        activity=None,
        topic=None,
        teaching_book_page_ranges=[],
        exercise_book_pages=[42],
        exercise="3.3",
        questions=questions,
        range_source="teacher_feedback",
        source_input_warning=None,
        selected_book_pages=pages,
        selected_pdf_pages=[page + 16 for page in pages],
        selected_page_count=len(pages),
        selection_is_contiguous=False,
        display_book_pages=None,
        display_pdf_pages=None,
        selection_policy="exact_union_of_teaching_ranges_and_exercise_pages",
        selected_pages_available=True,
    )


def test_teacher_schedule_day_reply_contains_plain_text_days_and_interactive_rows():
    service = ConversationService.__new__(ConversationService)
    lesson = _lesson()
    schedule = EmbeddingTeacherSchedule(
        id="schedule-1",
        document_id="doc-1",
        schedule_key="2026-08-17-ch3",
        chapter_number="3",
        chapter_title=lesson.chapter_title,
        section_number="3",
        section_title=lesson.section_title,
        week_start_date="2026-08-17",
        schedule_source="teacher_feedback",
        schedule_type="question_targeted_instruction",
        exercise="3.3",
        schedule_note=None,
        day_count=5,
    )
    days = [
        _day(1, "Monday", ["1(i)", "1(ii)"], [34, 35, 36, 37, 38, 39, 40, 42]),
        _day(2, "Tuesday", ["1(iii)", "1(iv)"], [35, 36, 37, 38, 39, 40, 41, 42]),
        _day(3, "Wednesday", ["2(i)", "2(ii)"], [36, 39, 40, 42]),
        _day(4, "Thursday", ["2(iii)", "2(iv)"], [39, 40, 41, 42]),
        _day(5, "Friday", ["2(v)"], [39, 40, 42]),
    ]

    reply = service._teacher_schedule_day_reply(
        lesson=lesson,
        schedule=schedule,
        days=days,
        summary="LESSON SUMMARY",
        language="hinglish",
    )

    assert "1. Monday — Questions: 1(i), 1(ii) — Book Pages 34-40, 42" in reply.reply
    assert "3. Wednesday — Questions: 2(i), 2(ii) — Book Pages 36, 39-40, 42" in reply.reply
    assert "5. Friday — Questions: 2(v) — Book Pages 39-40, 42" in reply.reply
    assert reply.reply.count("LESSON SUMMARY") == 1
    assert reply.outbound is not None
    assert reply.outbound["type"] == "list"
    assert len(reply.outbound["rows"]) == 6  # five scheduled days + Main Menu


def test_schedule_footer_stays_within_whatsapp_list_limit():
    service = ConversationService.__new__(ConversationService)
    assert len(service._text("Hinglish", "lesson_schedule_day_footer")) <= 60
    assert len(service._text("English", "lesson_schedule_day_footer")) <= 60
    assert len(service._text("Hindi", "lesson_schedule_day_footer")) <= 60
