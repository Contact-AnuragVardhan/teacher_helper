import re
from dataclasses import replace

from app.core.config import Settings
from app.models.teacher_profile import TeacherProfile
from app.repositories.embedding_content_repository import EmbeddingLessonMatch, EmbeddingSubsection
from app.services.lesson_pdf_service import LessonPdfService
from app.services.pdf_content_lesson_service import PdfContentLessonService
from app.services.prompt_builder import PromptBuilder


def _teacher(language: str) -> TeacherProfile:
    return TeacherProfile(
        whatsapp_number="+15550009999",
        teacher_name="Teacher",
        default_grade="9",
        default_subject="Mathematics",
        school_name="Sample School",
        preferred_language=language,
    )


def _lesson() -> EmbeddingLessonMatch:
    return EmbeddingLessonMatch(
        document_id="doc-1",
        chapter_id="chapter-1",
        document_key="book-1",
        school_name="Sample School",
        grade="9",
        class_name="Class9",
        subject="Mathematics",
        book_title="Mathematics",
        chapter_number="1",
        chapter_title="Number Systems",
        unit_number=None,
        unit_title=None,
        section_number="1",
        section_title="Number Systems",
        lesson_title=None,
        structure_type="chapter",
        pdf_start_page=10,
        pdf_end_page=20,
        printed_start_page="1",
        printed_end_page="11",
        text="Real numbers include rational and irrational numbers. Students compare their properties.",
        subsection_count=3,
    )


def _subsection() -> EmbeddingSubsection:
    return EmbeddingSubsection(
        id="sub-1",
        document_id="doc-1",
        subsection_number="Day1",
        subsection_title="Day 1",
        anchor_marker="Day 1",
        pdf_start_page=10,
        pdf_end_page=12,
        printed_start_page="1",
        printed_end_page="3",
        page_numbers=[10, 11, 12],
        printed_page_numbers=[1, 2, 3],
        includes=[],
        text="Real numbers include rational and irrational numbers. Compare examples from the textbook.",
        text_length_chars=88,
        include_in_embeddings=True,
        embedding_readiness="ready",
        quality_flags=[],
    )


def _service() -> PdfContentLessonService:
    return PdfContentLessonService(
        db=None,
        settings=Settings(database_url="sqlite://", llm_provider="deterministic"),
    )


def test_pdf_summary_prompt_explicitly_uses_profile_language():
    service = _service()
    prompt = service._section_summary_prompt(
        lesson=_lesson(),
        teacher=_teacher("Hindi"),
        grade="9",
        subject="Mathematics",
        duration_minutes=40,
        preferred_language="Hindi",
    )

    assert prompt.metadata["preferred_language"] == "Hindi"
    assert "Preferred Language: Hindi" in prompt.user_prompt
    assert "Hindi" in prompt.system_prompt
    assert "Devanagari" in prompt.system_prompt
    assert "5 to 7 short bullets" in prompt.user_prompt


def test_pdf_day_prompt_has_localized_hindi_shape():
    service = _service()
    prompt = service._day_lesson_prompt(
        lesson=_lesson(),
        subsection=_subsection(),
        day_number=1,
        teacher=_teacher("Hindi"),
        grade="9",
        subject="Mathematics",
        duration_minutes=40,
        preferred_language="Hindi",
    )

    assert prompt.metadata["preferred_language"] == "Hindi"
    assert "Preferred Language: Hindi" in prompt.user_prompt
    assert "📚 दिन 1 पाठ (विस्तृत)" in prompt.user_prompt
    assert "अध्याय: Number Systems" in prompt.user_prompt
    assert "विषय: गणित" in prompt.user_prompt
    assert "⭐ शिक्षक त्वरित दृश्य" in prompt.user_prompt
    assert "🏠 गृहकार्य" in prompt.user_prompt


def test_hindi_profile_controls_deterministic_day_lesson_and_header():
    service = _service()
    result = service.generate_day_lesson_plan(
        lesson=_lesson(),
        subsection=_subsection(),
        day_number=1,
        teacher=_teacher("English"),
        grade="9",
        subject="Mathematics",
        duration_minutes=40,
        preferred_language="Hindi",
    )

    assert result.provider_used == "deterministic"
    assert "*📚 दिन 1 पाठ (विस्तृत)*" in result.lesson_text
    assert "अध्याय: Number Systems" in result.lesson_text
    assert "विषय: गणित" in result.lesson_text
    assert "*⭐ शिक्षक त्वरित दृश्य*" in result.lesson_text
    assert "*🏠 गृहकार्य*" in result.lesson_text
    assert "Teacher Quick View" not in result.lesson_text
    assert "Lesson Overview" not in result.lesson_text


def test_hinglish_profile_controls_deterministic_day_lesson():
    service = _service()
    result = service.generate_day_lesson_plan(
        lesson=_lesson(),
        subsection=_subsection(),
        day_number=2,
        teacher=_teacher("English"),
        grade="9",
        subject="Mathematics",
        duration_minutes=35,
        preferred_language="Hinglish",
    )

    assert result.provider_used == "deterministic"
    assert "*📚 Day 2 Lesson (Detailed)*" in result.lesson_text
    assert "Students Number Systems ke selected part ko padhenge." in result.lesson_text
    assert "Difficult words ya steps ko simple Hinglish mein samjhayen." in result.lesson_text
    # This fixture contains only English source identifiers, so generated Hinglish should be Roman-only.
    assert not re.search(r"[\u0900-\u097F]", result.lesson_text)


def test_hindi_summary_fallback_is_profile_language_aware():
    service = _service()
    summary, provider = service.generate_section_summary(
        lesson=_lesson(),
        teacher=_teacher("English"),
        grade="9",
        subject="Mathematics",
        duration_minutes=40,
        preferred_language="Hindi",
    )

    assert provider == "deterministic"
    assert summary.startswith("- यह सारांश चुनी हुई पुस्तक सामग्री पर आधारित है।")
    assert "- पुस्तक पृष्ठ: 1-11" in summary
    assert "Chapter Summary" not in summary


def test_generic_prompt_builder_uses_same_central_language_rule():
    builder = PromptBuilder()
    assert "Devanagari script only" in builder._language_instruction("Hindi")
    assert "Roman script only" in builder._language_instruction("Hinglish")
    assert builder._language_instruction("English").endswith("English.")


def test_print_pdf_has_profile_language_labels():
    labels = LessonPdfService._labels_for_language("Hindi")
    assert labels["title"] == "विस्तृत पाठ योजना"
    assert labels["teacher"] == "शिक्षक"
    assert labels["book_pages"] == "पुस्तक पृष्ठ"
    assert labels["page"] == "पृष्ठ"


def test_poem_structure_type_uses_lesson_label_in_generated_prompt_and_output():
    service = _service()
    poem = replace(
        _lesson(),
        chapter_number="4",
        chapter_title="Amanda",
        section_number="4",
        section_title="Amanda",
        structure_type="poem",
    )

    prompt = service._day_lesson_prompt(
        lesson=poem,
        subsection=_subsection(),
        day_number=1,
        teacher=_teacher("English"),
        grade="10",
        subject="English",
        duration_minutes=40,
        preferred_language="English",
    )
    assert "Lesson: Amanda" in prompt.user_prompt
    assert "Chapter: Amanda" not in prompt.user_prompt

    result = service.generate_day_lesson_plan(
        lesson=poem,
        subsection=_subsection(),
        day_number=1,
        teacher=_teacher("English"),
        grade="10",
        subject="English",
        duration_minutes=40,
        preferred_language="English",
    )
    assert "Lesson: Amanda" in result.lesson_text
    assert "Chapter: Amanda" not in result.lesson_text
