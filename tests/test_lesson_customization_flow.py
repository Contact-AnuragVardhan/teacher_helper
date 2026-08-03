import base64
from io import BytesIO

from pypdf import PdfReader
from sqlalchemy import text

from app.models.lesson_plan import LessonPlan
from app.models.session_state import SessionState
from app.models.teacher_profile import TeacherProfile
from app.services.conversation_service import ConversationService
from app.services.pdf_content_lesson_service import PdfContentLessonResult
from app.state_machine.states import ConversationState


PHONE = "+15550007777"
DOC_ID = "doc-1"
CHAPTER_ID = "chapter-1"
SUBSECTION_ID = "subsection-1"


def _create_embedding_tables(db):
    statements = [
        """
        CREATE TABLE embeddings_documents (
            id TEXT PRIMARY KEY,
            document_key TEXT,
            school_name TEXT,
            grade TEXT,
            class_name TEXT,
            subject TEXT,
            book_title TEXT
        )
        """,
        """
        CREATE TABLE embeddings_book_chapters (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            chapter_number TEXT,
            chapter_title TEXT,
            unit_number TEXT,
            unit_title TEXT,
            section_number TEXT,
            section_title TEXT,
            lesson_title TEXT,
            structure_type TEXT,
            pdf_start_page INTEGER,
            pdf_end_page INTEGER,
            printed_start_page TEXT,
            printed_end_page TEXT
        )
        """,
        """
        CREATE TABLE embeddings_book_subsections (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            chapter_number TEXT,
            chapter_title TEXT,
            section_number TEXT,
            section_title TEXT,
            subsection_number TEXT,
            subsection_title TEXT,
            anchor_marker TEXT,
            pdf_start_page INTEGER,
            pdf_end_page INTEGER,
            printed_start_page TEXT,
            printed_end_page TEXT,
            page_numbers TEXT,
            printed_page_numbers TEXT,
            includes TEXT,
            subsection_text_plain TEXT,
            subsection_text TEXT,
            text_length_chars INTEGER,
            include_in_embeddings BOOLEAN,
            embedding_readiness TEXT,
            quality_flags TEXT
        )
        """,
        """
        CREATE TABLE embeddings_page_extractions (
            document_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
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
        """,
    ]
    for statement in statements:
        db.execute(text(statement))

    db.execute(
        text(
            """
            INSERT INTO embeddings_documents
                (id, document_key, school_name, grade, class_name, subject, book_title)
            VALUES
                (:id, 'sample-book', 'Sample School', '5', 'Class5', 'English', 'Sample Book')
            """
        ),
        {"id": DOC_ID},
    )
    db.execute(
        text(
            """
            INSERT INTO embeddings_book_chapters
                (id, document_id, chapter_number, chapter_title, section_number, section_title,
                 structure_type, pdf_start_page, pdf_end_page, printed_start_page, printed_end_page)
            VALUES
                (:id, :document_id, '1', 'Plants', '1', 'Plants',
                 'chapter', 10, 14, '1', '5')
            """
        ),
        {"id": CHAPTER_ID, "document_id": DOC_ID},
    )
    db.execute(
        text(
            """
            INSERT INTO embeddings_book_subsections
                (id, document_id, chapter_number, chapter_title, section_number, section_title,
                 subsection_number, subsection_title, anchor_marker,
                 pdf_start_page, pdf_end_page, printed_start_page, printed_end_page,
                 page_numbers, printed_page_numbers, includes,
                 subsection_text_plain, subsection_text, text_length_chars,
                 include_in_embeddings, embedding_readiness, quality_flags)
            VALUES
                (:id, :document_id, '1', 'Plants', '1', 'Plants',
                 'Day1', 'Day 1', 'Day 1',
                 11, 13, '2', '4',
                 '11,12,13', '2,3,4', '',
                 'Original day text', 'Original day text', 17,
                 1, 'ready', '')
            """
        ),
        {"id": SUBSECTION_ID, "document_id": DOC_ID},
    )
    for pdf_page, printed_page in zip(range(10, 15), range(1, 6)):
        db.execute(
            text(
                """
                INSERT INTO embeddings_page_extractions
                    (document_id, page_number, pdf_page_number, printed_page_number,
                     production_safe_text, include_in_lesson_text, include_in_embeddings, quality_flags)
                VALUES
                    (:document_id, :page_number, :pdf_page_number, :printed_page_number,
                     :page_text, 1, 1, '')
                """
            ),
            {
                "document_id": DOC_ID,
                "page_number": pdf_page,
                "pdf_page_number": pdf_page,
                "printed_page_number": str(printed_page),
                "page_text": f"UNIQUE PAGE {printed_page} CONTENT",
            },
        )
    db.commit()


def _prepare_generated_lesson_session(db):
    _create_embedding_tables(db)
    teacher = TeacherProfile(
        whatsapp_number=PHONE,
        teacher_name="Teacher",
        default_grade="5",
        default_subject="English",
        school_name="Sample School",
        preferred_language="English",
    )
    db.add(teacher)
    db.commit()
    db.refresh(teacher)

    session = SessionState(
        whatsapp_number=PHONE,
        current_state=ConversationState.NEW_LESSON_ACTION_MENU.value,
        temp_topic="Plants",
        temp_duration_minutes=35,
        temp_generated_lesson="ORIGINAL GENERATED LESSON",
        temp_profile_grade="5",
        temp_profile_subject="English",
        temp_content_document_id=DOC_ID,
        temp_content_chapter_id=CHAPTER_ID,
        temp_content_subsection_id=SUBSECTION_ID,
        temp_lesson_day_number=1,
        temp_lesson_day_title="Day 1",
        temp_lesson_book_title="Sample Book",
        temp_lesson_chapter_title="Plants",
        temp_lesson_section_title="Plants",
        temp_lesson_subsection_number="Day1",
        temp_lesson_subsection_title="Day 1",
        temp_lesson_book_pages="2-4",
        temp_lesson_pdf_start_page=11,
        temp_lesson_pdf_end_page=13,
        temp_lesson_printed_start_page="2",
        temp_lesson_printed_end_page="4",
        temp_lesson_document_key="sample-book",
        temp_lesson_school_name="Sample School",
        temp_lesson_is_customized=False,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return teacher, session


def test_use_this_lesson_preserves_existing_save_cancel_main_menu(db_session):
    _prepare_generated_lesson_session(db_session)
    service = ConversationService(db_session)

    reply = service.handle_message(PHONE, "use_generated_lesson")

    assert reply.current_state == ConversationState.NEW_LESSON_CONFIRM_SAVE.value
    assert reply.outbound["type"] == "buttons"
    assert [button["id"] for button in reply.outbound["buttons"]] == [
        "save_lesson",
        "cancel_lesson",
        "menu_main_menu",
    ]


def test_print_lesson_exports_pdf_and_keeps_action_menu(db_session):
    _prepare_generated_lesson_session(db_session)
    service = ConversationService(db_session)

    reply = service.handle_message(PHONE, "print_generated_lesson")

    assert reply.current_state == ConversationState.NEW_LESSON_ACTION_MENU.value
    assert "PDF is ready" in reply.reply
    assert reply.outbound["type"] == "sequence"
    document, buttons = reply.outbound["messages"]
    assert document["type"] == "document"
    assert document["filename"].endswith(".pdf")
    pdf_content = base64.b64decode(document["content_base64"])
    assert pdf_content.startswith(b"%PDF")
    reader = PdfReader(BytesIO(pdf_content))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Detailed Lesson Plan" in extracted
    assert "ORIGINAL GENERATED LESSON" in extracted
    assert buttons["type"] == "buttons"
    assert [button["id"] for button in buttons["buttons"]] == [
        "use_generated_lesson",
        "customize_generated_lesson",
        "print_generated_lesson",
    ]


def test_customize_pages_asks_from_then_to_regenerates_and_preserves_action_menu(db_session):
    _prepare_generated_lesson_session(db_session)
    service = ConversationService(db_session)
    captured = {}

    def fake_generate_day_lesson_plan(**kwargs):
        captured["subsection"] = kwargs["subsection"]
        return PdfContentLessonResult(
            lesson_text="CUSTOMIZED GENERATED LESSON",
            provider_used="test",
            duration_minutes=35,
        )

    service.pdf_content_lesson_service.generate_day_lesson_plan = fake_generate_day_lesson_plan

    customize_reply = service.handle_message(PHONE, "customize_generated_lesson")
    assert customize_reply.current_state == ConversationState.NEW_LESSON_CUSTOMIZE_FROM_PAGE.value
    assert "Current page range: 2-4" in customize_reply.reply
    assert "Chapter page range: 1-5" in customize_reply.reply
    assert "Enter the new From Page" in customize_reply.reply

    to_prompt = service.handle_message(PHONE, "1")
    assert to_prompt.current_state == ConversationState.NEW_LESSON_CUSTOMIZE_TO_PAGE.value
    assert "Selected From Page: 1" in to_prompt.reply
    assert "Enter the new To Page" in to_prompt.reply

    generated_reply = service.handle_message(PHONE, "3")
    assert generated_reply.current_state == ConversationState.NEW_LESSON_ACTION_MENU.value
    assert "CUSTOMIZED GENERATED LESSON" in generated_reply.reply
    assert [button["id"] for button in generated_reply.outbound["buttons"]] == [
        "use_generated_lesson",
        "customize_generated_lesson",
        "print_generated_lesson",
    ]

    selected = captured["subsection"]
    assert selected.pdf_start_page == 10
    assert selected.pdf_end_page == 12
    assert selected.printed_start_page == "1"
    assert selected.printed_end_page == "3"
    assert "UNIQUE PAGE 1 CONTENT" in selected.text
    assert "UNIQUE PAGE 2 CONTENT" in selected.text
    assert "UNIQUE PAGE 3 CONTENT" in selected.text
    assert "UNIQUE PAGE 4 CONTENT" not in selected.text
    assert "UNIQUE PAGE 5 CONTENT" not in selected.text

    use_reply = service.handle_message(PHONE, "use_generated_lesson")
    assert use_reply.current_state == ConversationState.NEW_LESSON_CONFIRM_SAVE.value

    name_reply = service.handle_message(PHONE, "save_lesson")
    assert name_reply.current_state == ConversationState.NEW_LESSON_CONFIRM_NAME.value
    assert "*" in name_reply.reply

    assert service.handle_message(PHONE, "no").current_state == ConversationState.NEW_LESSON_NAME.value
    saved_reply = service.handle_message(PHONE, "My Customized Lesson")
    assert saved_reply.current_state == ConversationState.MAIN_MENU.value

    saved = db_session.query(LessonPlan).one()
    assert saved.lesson_name == "My Customized Lesson*"
    assert saved.book_pages == "1-3"
    assert saved.pdf_start_page == 10
    assert saved.pdf_end_page == 12
    assert saved.printed_start_page == "1"
    assert saved.printed_end_page == "3"
    assert saved.lesson_payload["source_type"] == "pdf_to_embeddings_page_range"
    assert saved.lesson_payload["is_customized"] is True


def test_customize_rejects_page_outside_current_chapter(db_session):
    _prepare_generated_lesson_session(db_session)
    service = ConversationService(db_session)

    service.handle_message(PHONE, "customize_generated_lesson")
    reply = service.handle_message(PHONE, "99")

    assert reply.current_state == ConversationState.NEW_LESSON_CUSTOMIZE_FROM_PAGE.value
    assert "not inside the current chapter" in reply.reply
    assert "Enter the new From Page" in reply.reply


def test_customize_rejects_reversed_range_and_back_returns_to_generated_menu(db_session):
    _prepare_generated_lesson_session(db_session)
    service = ConversationService(db_session)

    service.handle_message(PHONE, "customize_generated_lesson")
    assert service.handle_message(PHONE, "4").current_state == ConversationState.NEW_LESSON_CUSTOMIZE_TO_PAGE.value
    invalid = service.handle_message(PHONE, "2")

    assert invalid.current_state == ConversationState.NEW_LESSON_CUSTOMIZE_TO_PAGE.value
    assert "From Page cannot be after To Page" in invalid.reply
    assert "Enter the new To Page" in invalid.reply

    back = service.handle_message(PHONE, "back")
    assert back.current_state == ConversationState.NEW_LESSON_ACTION_MENU.value
    assert [button["id"] for button in back.outbound["buttons"]] == [
        "use_generated_lesson",
        "customize_generated_lesson",
        "print_generated_lesson",
    ]


def test_page_choice_accepts_compound_printed_labels(db_session):
    _prepare_generated_lesson_session(db_session)
    db_session.execute(
        text(
            """
            UPDATE embeddings_page_extractions
            SET printed_page_number = '2/4'
            WHERE pdf_page_number = 10
            """
        )
    )
    db_session.commit()
    service = ConversationService(db_session)
    lesson = service.embedding_content_repo.get_lesson_by_chapter_id(CHAPTER_ID)
    pages = service.embedding_content_repo.list_pages_for_lesson(lesson)

    selected = service.embedding_content_repo.resolve_page_choice(pages, "2/4")

    assert selected is not None
    assert selected.pdf_page_number == 10
    assert selected.display_page == "2/4"


def test_customize_rejects_missing_physical_page_gap(db_session):
    _prepare_generated_lesson_session(db_session)
    db_session.execute(text("DELETE FROM embeddings_page_extractions WHERE pdf_page_number = 12"))
    db_session.commit()
    service = ConversationService(db_session)

    service.handle_message(PHONE, "customize_generated_lesson")
    assert service.handle_message(PHONE, "1").current_state == ConversationState.NEW_LESSON_CUSTOMIZE_TO_PAGE.value
    reply = service.handle_message(PHONE, "4")

    assert reply.current_state == ConversationState.NEW_LESSON_CUSTOMIZE_TO_PAGE.value
    assert "every selected page must be contiguous" in reply.reply
    assert "Enter the new To Page" in reply.reply
