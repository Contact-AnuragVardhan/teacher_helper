from sqlalchemy import text

from app.repositories.embedding_content_repository import (
    EmbeddingContentRepository,
    EmbeddingLessonMatch,
)


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


def test_teacher_schedule_tables_are_optional_for_old_books(db_session):
    repo = EmbeddingContentRepository(db_session)

    # The normal Teacher Helper app DB does not own these external embedding
    # tables. Missing schedule tables must be treated as "no optional schedule"
    # rather than breaking the existing structural-day flow.
    assert repo.list_teacher_schedules_for_lesson(_lesson()) == []
    assert db_session.execute(text("SELECT 1")).scalar_one() == 1


def test_teacher_schedule_exact_non_contiguous_pages_build_day_source(db_session):
    conn = db_session.connection()
    conn.execute(text("""
        CREATE TABLE embeddings_teacher_schedules (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            schedule_key TEXT,
            chapter_number TEXT,
            chapter_title TEXT,
            section_number TEXT,
            section_title TEXT,
            week_start_date TEXT,
            schedule_source TEXT,
            schedule_type TEXT,
            exercise TEXT,
            schedule_note TEXT
        )
    """))
    conn.execute(text("""
        CREATE TABLE embeddings_teacher_schedule_days (
            id TEXT PRIMARY KEY,
            teacher_schedule_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            day INTEGER,
            weekday TEXT,
            day_type TEXT,
            activity TEXT,
            topic TEXT,
            teaching_book_page_ranges TEXT,
            exercise_book_pages TEXT,
            exercise TEXT,
            questions TEXT,
            range_source TEXT,
            source_input_warning TEXT,
            selected_book_pages TEXT,
            selected_pdf_pages TEXT,
            selected_page_count INTEGER,
            selection_is_contiguous BOOLEAN,
            display_book_pages TEXT,
            display_pdf_pages TEXT,
            selection_policy TEXT,
            selected_pages_available BOOLEAN
        )
    """))
    conn.execute(text("""
        CREATE TABLE embeddings_page_extractions (
            document_id TEXT NOT NULL,
            pdf_page_number INTEGER NOT NULL,
            printed_page_number TEXT,
            printed_page_label TEXT,
            production_safe_text TEXT,
            production_page_text TEXT,
            text_plain TEXT,
            text TEXT,
            selectable_text TEXT,
            raw_extracted_text TEXT,
            ocr_text TEXT,
            include_in_lesson_text BOOLEAN,
            include_in_embeddings BOOLEAN,
            quality_flags TEXT
        )
    """))
    conn.execute(
        text("""
            INSERT INTO embeddings_teacher_schedules(
                id, document_id, schedule_key, chapter_number, chapter_title,
                section_number, section_title, week_start_date, schedule_source,
                schedule_type, exercise, schedule_note
            ) VALUES (
                'schedule-1', 'doc-1', '2026-08-17-ch3', '3',
                'दो चर वाले रैखिक समीकरण युग्म', '3',
                'दो चर वाले रैखिक समीकरण युग्म', '2026-08-17',
                'teacher_feedback', 'question_targeted_instruction', '3.3', 'note'
            )
        """)
    )
    conn.execute(
        text("""
            INSERT INTO embeddings_teacher_schedule_days(
                id, teacher_schedule_id, document_id, day, weekday, day_type,
                activity, topic, teaching_book_page_ranges, exercise_book_pages,
                exercise, questions, range_source, source_input_warning,
                selected_book_pages, selected_pdf_pages, selected_page_count,
                selection_is_contiguous, display_book_pages, display_pdf_pages,
                selection_policy, selected_pages_available
            ) VALUES (
                'day-3', 'schedule-1', 'doc-1', 3, 'Wednesday', 'instruction',
                'Exercise 3.3 Question 2 (i, ii)', 'Word problems',
                :ranges, :exercise_pages, '3.3', :questions, 'teacher_feedback', NULL,
                :book_pages, :pdf_pages, 4, 0,
                '36, 39, 40, 42', '52, 55, 56, 58',
                'exact_union_of_teaching_ranges_and_exercise_pages', 1
            )
        """),
        {
            "ranges": '[{"start_book_page":36,"end_book_page":36},{"start_book_page":39,"end_book_page":40}]',
            "exercise_pages": "[42]",
            "questions": '["2(i)","2(ii)"]',
            "book_pages": "[36,39,40,42]",
            "pdf_pages": "[52,55,56,58]",
        },
    )
    for pdf_page in range(44, 59):
        book_page = pdf_page - 16
        conn.execute(
            text("""
                INSERT INTO embeddings_page_extractions(
                    document_id, pdf_page_number, printed_page_number,
                    printed_page_label, production_safe_text,
                    include_in_lesson_text, include_in_embeddings
                ) VALUES (:document_id, :pdf_page, :book_page, :book_page, :content, 1, 1)
            """),
            {
                "document_id": "doc-1",
                "pdf_page": pdf_page,
                "book_page": str(book_page),
                "content": f"CONTENT FOR BOOK PAGE {book_page}",
            },
        )
    db_session.commit()

    repo = EmbeddingContentRepository(db_session)
    lesson = _lesson()
    schedules = repo.list_teacher_schedules_for_lesson(lesson)
    assert len(schedules) == 1
    assert schedules[0].exercise == "3.3"

    days = repo.list_teacher_schedule_days(schedules[0].id)
    assert len(days) == 1
    assert days[0].selected_book_pages == [36, 39, 40, 42]
    assert days[0].questions == ["2(i)", "2(ii)"]

    subsection = repo.build_subsection_from_teacher_schedule_day(lesson, schedules[0], days[0])
    assert subsection is not None
    assert subsection.source_kind == "teacher_schedule_day"
    assert subsection.display_pages == "36, 39-40, 42"
    assert subsection.page_numbers == [52, 55, 56, 58]
    assert subsection.schedule_exercise == "3.3"
    assert subsection.schedule_questions == ["2(i)", "2(ii)"]
    assert "CONTENT FOR BOOK PAGE 36" in subsection.text
    assert "CONTENT FOR BOOK PAGE 39" in subsection.text
    assert "CONTENT FOR BOOK PAGE 40" in subsection.text
    assert "CONTENT FOR BOOK PAGE 42" in subsection.text
    assert "CONTENT FOR BOOK PAGE 37" not in subsection.text
    assert "CONTENT FOR BOOK PAGE 38" not in subsection.text
    assert "CONTENT FOR BOOK PAGE 41" not in subsection.text
