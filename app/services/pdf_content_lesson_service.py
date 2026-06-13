from __future__ import annotations

import re
from dataclasses import dataclass

from openai import OpenAI
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.language import language_key
from app.core.logging import get_logger, log_event
from app.models.teacher_profile import TeacherProfile
from app.repositories.embedding_content_repository import EmbeddingLessonMatch, EmbeddingSubsection
from app.services.lesson_generation_provider import PromptBundle
from app.services.output_normalizer import normalize_lesson_output
from app.services.whatsapp_formatter import format_whatsapp_lesson
from app.utils.subject_normalization import normalize_subject, subject_display_name

logger = get_logger(__name__)


@dataclass(slots=True)
class PdfContentLessonResult:
    lesson_text: str
    provider_used: str
    duration_minutes: int


class PdfContentLessonService:
    """LLM tasks that use exact content imported by pdf_to_embeddings."""

    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()

    def generate_section_summary(
        self,
        *,
        lesson: EmbeddingLessonMatch,
        teacher: TeacherProfile,
        grade: str | None = None,
        subject: str | None = None,
        duration_minutes: int | None = None,
    ) -> tuple[str, str]:
        prompt = self._section_summary_prompt(lesson=lesson, teacher=teacher, grade=grade, subject=subject, duration_minutes=duration_minutes)
        self._log_section_db_text(lesson=lesson, teacher=teacher, grade=grade, subject=subject, duration_minutes=duration_minutes)
        fallback = self._fallback_section_summary(
            lesson,
            language=getattr(teacher, "preferred_language", "English"),
        )
        raw_summary, provider_used = self._generate_or_fallback(
            prompt,
            fallback=fallback,
            task="section_summary",
            context={
                "document_id": lesson.document_id,
                "document_key": lesson.document_key,
                "chapter_id": lesson.chapter_id,
                "lesson_title": lesson.title,
            },
        )
        normalized_summary = normalize_lesson_output(raw_summary)
        log_event(
            logger,
            "pdf_content_section_summary_processed",
            document_id=lesson.document_id,
            document_key=lesson.document_key,
            chapter_id=lesson.chapter_id,
            lesson_title=lesson.title,
            provider_used=provider_used,
            raw_output_length=len(raw_summary),
            normalized_output_length=len(normalized_summary),
            raw_llm_output=raw_summary,
            normalized_llm_output=normalized_summary,
        )
        return normalized_summary, provider_used

    def generate_day_lesson_plan(
        self,
        *,
        lesson: EmbeddingLessonMatch,
        subsection: EmbeddingSubsection,
        day_number: int,
        teacher: TeacherProfile,
        grade: str | None = None,
        subject: str | None = None,
        duration_minutes: int | None = None,
    ) -> PdfContentLessonResult:
        prompt = self._day_lesson_prompt(
            lesson=lesson,
            subsection=subsection,
            day_number=day_number,
            teacher=teacher,
            grade=grade,
            subject=subject,
            duration_minutes=duration_minutes,
        )
        self._log_subsection_db_text(lesson=lesson, subsection=subsection, day_number=day_number, teacher=teacher, grade=grade, subject=subject, duration_minutes=duration_minutes)
        fallback = self._fallback_day_lesson_plan(
            lesson=lesson,
            subsection=subsection,
            day_number=day_number,
            teacher=teacher,
            grade=grade,
            subject=subject,
            duration_minutes=duration_minutes,
        )
        raw_lesson_text, provider_used = self._generate_or_fallback(
            prompt,
            fallback=fallback,
            task="day_lesson_plan",
            context={
                "document_id": lesson.document_id,
                "document_key": lesson.document_key,
                "chapter_id": lesson.chapter_id,
                "subsection_id": subsection.id,
                "lesson_title": lesson.title,
                "subsection_title": subsection.title,
                "day_number": day_number,
                "book_pages": subsection.display_pages,
                "teacher_input_grade": grade,
                "teacher_input_subject": subject,
                "teacher_input_duration_minutes": duration_minutes,
            },
        )
        normalized_lesson_text = normalize_lesson_output(raw_lesson_text)
        whatsapp_lesson_text = format_whatsapp_lesson(normalized_lesson_text)
        whatsapp_lesson_text = self._strip_trailing_lesson_conclusion(whatsapp_lesson_text)
        whatsapp_lesson_text = self._ensure_day_lesson_header_metadata(
            whatsapp_lesson_text,
            lesson=lesson,
            subsection=subsection,
            day_number=day_number,
            teacher=teacher,
            grade=grade,
            subject=subject,
            duration_minutes=duration_minutes,
        )
        duration = duration_minutes or self._extract_duration_minutes(whatsapp_lesson_text) or self._extract_duration_minutes(normalized_lesson_text) or 40
        log_event(
            logger,
            "pdf_content_day_lesson_output_processed",
            document_id=lesson.document_id,
            document_key=lesson.document_key,
            chapter_id=lesson.chapter_id,
            subsection_id=subsection.id,
            lesson_title=lesson.title,
            subsection_title=subsection.title,
            day_number=day_number,
            teacher_input_grade=grade,
            teacher_input_subject=subject,
            teacher_input_duration_minutes=duration_minutes,
            provider_used=provider_used,
            raw_output_length=len(raw_lesson_text),
            normalized_output_length=len(normalized_lesson_text),
            whatsapp_output_length=len(whatsapp_lesson_text),
            raw_llm_output=raw_lesson_text,
            normalized_llm_output=normalized_lesson_text,
            whatsapp_lesson_output=whatsapp_lesson_text,
        )
        return PdfContentLessonResult(lesson_text=whatsapp_lesson_text, provider_used=provider_used, duration_minutes=duration)

    def _generate_or_fallback(
        self,
        prompt: PromptBundle,
        *,
        fallback: str,
        task: str,
        context: dict | None = None,
    ) -> tuple[str, str]:
        context = context or {}
        self._log_prompt(prompt=prompt, task=task, context=context)
        if self.settings.llm_provider != "openai" or not self.settings.openai_api_key:
            log_event(
                logger,
                "pdf_content_lesson_llm_skipped",
                task=task,
                configured_provider=self.settings.llm_provider,
                has_openai_key=bool(self.settings.openai_api_key),
                fallback_output_length=len(fallback),
                fallback_output=fallback,
                **context,
            )
            return fallback, "deterministic"

        try:
            client_kwargs: dict[str, str] = {"api_key": self.settings.openai_api_key}
            if self.settings.openai_base_url:
                client_kwargs["base_url"] = self.settings.openai_base_url
            client = OpenAI(**client_kwargs)
            response = client.chat.completions.create(
                model=self.settings.openai_model,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": prompt.system_prompt},
                    {"role": "user", "content": prompt.user_prompt},
                ],
            )
            content = (response.choices[0].message.content if response.choices else "") or ""
            content = content.strip()
            if not content:
                raise RuntimeError("empty LLM response")
            log_event(
                logger,
                "pdf_content_lesson_llm_completed",
                task=task,
                model=self.settings.openai_model,
                raw_output_length=len(content),
                raw_llm_output=content,
                **context,
            )
            return content, "openai"
        except Exception as exc:  # pragma: no cover - defensive fallback for production availability.
            log_event(
                logger,
                "pdf_content_lesson_llm_fallback",
                task=task,
                error=str(exc),
                fallback_output_length=len(fallback),
                fallback_output=fallback,
                **context,
            )
            return fallback, "deterministic"


    def _log_section_db_text(
        self,
        *,
        lesson: EmbeddingLessonMatch,
        teacher: TeacherProfile,
        grade: str | None = None,
        subject: str | None = None,
        duration_minutes: int | None = None,
    ) -> None:
        lesson_text = self._safe_lesson_text(lesson.text)
        log_event(
            logger,
            "pdf_content_section_db_text_loaded",
            document_id=lesson.document_id,
            document_key=lesson.document_key,
            chapter_id=lesson.chapter_id,
            school_name=getattr(teacher, "school_name", None) or lesson.school_name,
            grade=grade or lesson.grade or lesson.class_name or teacher.default_grade,
            subject=subject or lesson.subject or teacher.default_subject,
            teacher_input_grade=grade,
            teacher_input_subject=subject,
            teacher_input_duration_minutes=duration_minutes,
            lesson_title=lesson.title,
            book_title=lesson.book_title,
            book_pages=lesson.display_pages,
            subsection_count=lesson.subsection_count,
            text_length=len(lesson_text),
            db_lesson_text=lesson_text,
        )

    def _log_subsection_db_text(
        self,
        *,
        lesson: EmbeddingLessonMatch,
        subsection: EmbeddingSubsection,
        day_number: int,
        teacher: TeacherProfile,
        grade: str | None = None,
        subject: str | None = None,
        duration_minutes: int | None = None,
    ) -> None:
        subsection_text = (subsection.text or "").strip()
        log_event(
            logger,
            "pdf_content_subsection_db_text_loaded",
            document_id=lesson.document_id,
            document_key=lesson.document_key,
            chapter_id=lesson.chapter_id,
            subsection_id=subsection.id,
            school_name=getattr(teacher, "school_name", None) or lesson.school_name,
            grade=grade or lesson.grade or lesson.class_name or teacher.default_grade,
            subject=subject or lesson.subject or teacher.default_subject,
            teacher_input_grade=grade,
            teacher_input_subject=subject,
            teacher_input_duration_minutes=duration_minutes,
            lesson_title=lesson.title,
            subsection_number=subsection.subsection_number,
            subsection_title=subsection.title,
            anchor_marker=subsection.anchor_marker,
            day_number=day_number,
            book_pages=subsection.display_pages,
            pdf_start_page=subsection.pdf_start_page,
            pdf_end_page=subsection.pdf_end_page,
            printed_start_page=subsection.printed_start_page,
            printed_end_page=subsection.printed_end_page,
            page_numbers=subsection.page_numbers,
            printed_page_numbers=subsection.printed_page_numbers,
            includes=subsection.includes,
            text_length=len(subsection_text),
            db_subsection_text=subsection_text,
            embedding_readiness=subsection.embedding_readiness,
            quality_flags=subsection.quality_flags,
        )

    def _log_prompt(self, *, prompt: PromptBundle, task: str, context: dict) -> None:
        log_event(
            logger,
            "pdf_content_lesson_prompt_prepared",
            task=task,
            model=self.settings.openai_model,
            system_prompt_length=len(prompt.system_prompt or ""),
            user_prompt_length=len(prompt.user_prompt or ""),
            total_prompt_length=len(prompt.system_prompt or "") + len(prompt.user_prompt or ""),
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            total_prompt=f"SYSTEM:\n{prompt.system_prompt}\n\nUSER:\n{prompt.user_prompt}",
            prompt_metadata=prompt.metadata,
            **context,
        )

    def _section_summary_prompt(
        self,
        *,
        lesson: EmbeddingLessonMatch,
        teacher: TeacherProfile,
        grade: str | None = None,
        subject: str | None = None,
        duration_minutes: int | None = None,
    ) -> PromptBundle:
        lesson_text = self._safe_lesson_text(lesson.text)
        grade_value = grade or lesson.grade or lesson.class_name or teacher.default_grade
        subject_value = subject_display_name(normalize_subject(subject or lesson.subject or teacher.default_subject), language=getattr(teacher, "preferred_language", "English"))
        system_prompt = (
            "You are a helpful teaching assistant for resource-limited classrooms. "
            "You summarize textbook chapter content for a teacher before they choose a day."
        )
        user_prompt = (
            "Generate a simple chapter summary for the teacher.\n\n"
            f"School: {getattr(teacher, 'school_name', '') or lesson.school_name or ''}\n"
            f"Grade: {grade_value}\n"
            f"Subject: {subject_value}\n"
            f"Class Duration: {duration_minutes or 0} minutes\n"
            f"Book: {lesson.book_title or ''}\n"
            f"Chapter: {lesson.title}\n"
            f"Book pages: {lesson.display_pages}\n\n"
            "Rules:\n"
            "- Use ONLY the supplied chapter content.\n"
            "- Keep it WhatsApp friendly.\n"
            "- Do not create a lesson plan yet.\n"
            "- Write 5 to 7 short bullets.\n"
            "- Mention the main idea, important vocabulary/concepts, and what students will practice.\n"
            "- No markdown tables. No HTML. No LaTeX.\n\n"
            "--- CHAPTER CONTENT START ---\n"
            f"{lesson_text}\n"
            "--- CHAPTER CONTENT END ---"
        )
        return PromptBundle(system_prompt=system_prompt, user_prompt=user_prompt, metadata={"task": "section_summary", "grade": grade_value, "subject": subject_value, "duration_minutes": duration_minutes})

    def _day_lesson_prompt(
        self,
        *,
        lesson: EmbeddingLessonMatch,
        subsection: EmbeddingSubsection,
        day_number: int,
        teacher: TeacherProfile,
        grade: str | None = None,
        subject: str | None = None,
        duration_minutes: int | None = None,
    ) -> PromptBundle:
        subject_normalized = normalize_subject(subject or lesson.subject or teacher.default_subject)
        subject_display = subject_display_name(subject_normalized, language=getattr(teacher, "preferred_language", "English"))
        grade = grade or lesson.grade or lesson.class_name or teacher.default_grade
        requested_duration = int(duration_minutes or 40)
        chapter = lesson.title
        book_title = (lesson.book_title or "").strip() or "Selected textbook"
        book_pages = subsection.display_pages
        day_title = f"Day {day_number}"
        day_content = subsection.text.strip()

        # Keep this prompt intentionally close to PlanB's day_detailed prompt.
        # Teacher Helper still preserves the existing teacher inputs
        # (grade, subject, chapter, book, and class duration), but the core
        # instruction/order mirrors PlanB so OpenAI output is less likely to
        # add extra commentary.
        system_prompt = "You are generating a DETAILED LESSON PLAN for ONE DAY only."
        user_prompt = (
            "You are generating a DETAILED LESSON PLAN for ONE DAY only.\n\n"
            f"This is {day_title}.\n\n"
            f"Grade: {grade}\n"
            f"Subject: {subject_display}\n"
            f"Chapter: {chapter}\n"
            f"Book: {book_title}\n"
            f"Class Duration: {requested_duration} minutes\n"
            "Resource Profile: Resource-Limited\n"
            "Format Profile: Detailed\n\n"
            "Use ONLY the supplied DAY content.\n"
            "Do NOT use other chapter content.\n"
            "Do NOT use content from previous days.\n"
            "Do NOT use content from later days.\n"
            "Do NOT generate a chapter summary.\n"
            "Do NOT generate a multi-day plan.\n\n"
            "Base the lesson only on:\n"
            "- supplied DAY content\n"
            "- supplied book page range\n\n"
            "Book pages:\n"
            f"{book_pages}\n\n"
            "Required output format (use these section headers with emojis):\n"
            f"📚 {day_title} Lesson (Detailed)\n"
            f"Chapter: {chapter}\n"
            f"Book: {book_title}\n"
            f"Book Pages: {book_pages}\n"
            f"Grade: {grade}\n"
            f"Subject: {subject_display}\n"
            f"Class Duration: {requested_duration} minutes\n"
            "Resource Profile: Resource-Limited\n"
            f"⏱ Total lesson time: ~{requested_duration} minutes\n\n"
            "⭐ Teacher Quick View\n\n"
            "📚 Lesson Overview\n\n"
            "🎯 Learning Goal\n\n"
            "🧰 Materials Needed\n\n"
            "👩‍🏫 Teacher Explanation\n\n"
            "📖 Book Connection\n\n"
            "👥 Student Activity\n\n"
            "✅ Check Understanding\n\n"
            "🏠 Homework\n\n"
            "Required qualities:\n"
            "- WhatsApp friendly\n"
            "- Teacher friendly\n"
            "- Resource limited\n"
            "- Book connected\n"
            "- Time friendly\n"
            "- Student friendly\n\n"
            "WhatsApp formatting rules:\n"
            "- Short sentences.\n"
            "- Each sentence on a new line when practical.\n"
            "- No long paragraphs.\n"
            "- No Markdown tables.\n"
            "- No HTML.\n"
            "- No LaTeX.\n"
            "- Fractions as 3/5, 17/6, 2 1/3.\n"
            "- Use examples from supplied content.\n"
            "- Refer to the book pages provided.\n"
            "- Use only resource-limited materials.\n"
            f"- Keep the whole lesson within {requested_duration} minutes.\n"
            "- Do not include any source block or YouTube link.\n"
            "- End the response immediately after the Homework section.\n"
            "- Do not add any final note, summary, conclusion, or closing sentence after Homework.\n\n"
            f"--- {day_title.upper()} CONTENT START ---\n"
            f"{day_content}\n"
            f"--- {day_title.upper()} CONTENT END ---"
        )
        return PromptBundle(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            metadata={
                "task": "day_lesson_plan",
                "grade": grade,
                "subject": subject_display,
                "chapter": chapter,
                "book_title": book_title,
                "day_number": day_number,
                "book_pages": book_pages,
                "duration_minutes": requested_duration,
            },
        )

    def _strip_trailing_lesson_conclusion(self, text: str) -> str:
        """Remove generic LLM-added closing sentences after Homework.

        PlanB does not have a special conclusion section. Teacher Helper should
        therefore end at the Homework section too. This keeps the existing
        teacher-question flow unchanged while making the final output closer to
        PlanB and preventing generic lines like:
        "This lesson plan is designed to..."
        """
        if not text:
            return text

        lines = text.rstrip().splitlines()
        while lines and not lines[-1].strip():
            lines.pop()

        generic_patterns = [
            r"^this lesson plan is designed to\b",
            r"^this lesson is designed to\b",
            r"^this lesson will engage\b",
            r"^overall,\s*this lesson\b",
            r"^in conclusion\b",
            r"^to conclude\b",
            r"^finally,\s*this lesson\b",
        ]

        # Remove one or more generic trailing closing lines.
        while lines:
            last = lines[-1].strip()
            if any(re.match(pattern, last, flags=re.IGNORECASE) for pattern in generic_patterns):
                lines.pop()
                while lines and not lines[-1].strip():
                    lines.pop()
                continue
            break

        return "\n".join(lines).rstrip()

    def _safe_lesson_text(self, value: str) -> str:
        text = (value or "").strip()
        if len(text) <= 24000:
            return text
        # Summary generation can work from a long but bounded excerpt; the day lesson prompt still receives exact day text.
        return text[:24000].rsplit("\n", 1)[0]

    def _fallback_section_summary(self, lesson: EmbeddingLessonMatch, language: str = "English") -> str:
        text = re.sub(r"\s+", " ", (lesson.text or "").strip())
        preview = text[:700].strip()
        days_word = "day" if int(lesson.subsection_count or 0) == 1 else "days"
        lang = language_key(language)
        if preview:
            preview = preview + ("..." if len(text) > 700 else "")
        else:
            if lang == "hindi":
                preview = "सारांश उपलब्ध नहीं है क्योंकि embeddings tables में chapter text नहीं मिला।"
            elif lang == "hinglish":
                preview = "Summary available nahi hai kyunki embeddings tables mein chapter text nahi mila."
            else:
                preview = "Summary is not available because no chapter text was found in the embeddings tables."
        if lang == "hindi":
            return (
                f"अध्याय सारांश\n"
                f"अध्याय: {lesson.title}\n"
                f"Book Pages: {lesson.display_pages}\n\n"
                f"- यह अध्याय textbook content database से match हुआ है।\n"
                f"- इसमें {lesson.subsection_count} दिन हैं।\n"
                f"- Preview: {preview}"
            )
        if lang == "hinglish":
            return (
                f"Chapter Summary\n"
                f"Chapter: {lesson.title}\n"
                f"Book Pages: {lesson.display_pages}\n\n"
                f"- Yeh chapter textbook content database se match hua hai.\n"
                f"- Ismein {lesson.subsection_count} {days_word} hain.\n"
                f"- Preview: {preview}"
            )
        return (
            f"Chapter Summary\n"
            f"Chapter: {lesson.title}\n"
            f"Book Pages: {lesson.display_pages}\n\n"
            f"- This chapter is matched from the textbook content database.\n"
            f"- It has {lesson.subsection_count} {days_word}.\n"
            f"- Preview: {preview}"
        )

    def _fallback_day_lesson_plan(
        self,
        *,
        lesson: EmbeddingLessonMatch,
        subsection: EmbeddingSubsection,
        day_number: int,
        teacher: TeacherProfile,
        grade: str | None = None,
        subject: str | None = None,
        duration_minutes: int | None = None,
    ) -> str:
        subject = subject_display_name(normalize_subject(subject or lesson.subject or teacher.default_subject), language="English")
        grade = grade or lesson.grade or lesson.class_name or teacher.default_grade
        requested_duration = int(duration_minutes or 40)
        chapter = lesson.title
        book_title = (lesson.book_title or "").strip() or "Selected textbook"
        book_pages = subsection.display_pages
        return (
            f"📚 Day {day_number} Lesson (Detailed)\n"
            f"Chapter: {chapter}\n"
            f"Book: {book_title}\n"
            f"Book Pages: {book_pages}\n"
            f"Grade: {grade}\n"
            f"Subject: {subject}\n"
            f"Class Duration: {requested_duration} minutes\n"
            "Resource Profile: Resource-Limited\n"
            f"⏱ Total lesson time: ~{requested_duration} minutes\n\n"
            "⭐ Teacher Quick View\n"
            f"Grade: {grade}\n"
            f"Subject: {subject}\n"
            f"Class Duration: {requested_duration} minutes\n"
            f"Use only Day {day_number} textbook content.\n\n"
            "📚 Lesson Overview\n"
            f"Students will study the selected part of {chapter}.\n"
            "The teacher should connect explanation directly to the book lines and activities.\n\n"
            "🎯 Learning Goal\n"
            "Students will understand the main idea from the supplied day content.\n"
            "Students will answer short oral or written questions from the book pages.\n\n"
            "🧰 Materials Needed\n"
            "Textbook.\n"
            "Blackboard or notebook.\n"
            "Chalk or pencil.\n\n"
            "👩‍🏫 Teacher Explanation\n"
            "Read the selected book content aloud.\n"
            "Pause after important lines.\n"
            "Explain difficult words or steps in simple language.\n\n"
            "📖 Book Connection\n"
            f"Ask students to look at book pages {book_pages}.\n"
            "Use examples and questions only from these pages.\n\n"
            "👥 Student Activity\n"
            "Students work in pairs.\n"
            "Each pair finds two important points from the day content.\n"
            "A few students share answers with the class.\n\n"
            "✅ Check Understanding\n"
            "Ask two short questions from the supplied content.\n"
            "Ask one student to explain the main idea in one sentence.\n\n"
            "🏠 Homework\n"
            "Revise the selected book pages.\n"
            "Write three lines about what you understood today."
        )

    def _ensure_day_lesson_header_metadata(
        self,
        text: str,
        *,
        lesson: EmbeddingLessonMatch,
        subsection: EmbeddingSubsection,
        day_number: int,
        teacher: TeacherProfile,
        grade: str | None = None,
        subject: str | None = None,
        duration_minutes: int | None = None,
    ) -> str:
        """Ensure the visible WhatsApp lesson starts with teacher-entered metadata.

        The LLM is asked to include these lines, but this deterministic pass keeps
        the saved/sent lesson consistent even if the model omits or reorders them.
        """
        subject_display = subject_display_name(
            normalize_subject(subject or lesson.subject or teacher.default_subject),
            language=getattr(teacher, "preferred_language", "English"),
        )
        grade_value = grade or lesson.grade or lesson.class_name or teacher.default_grade
        requested_duration = int(duration_minutes or self._extract_duration_minutes(text) or 40)
        chapter = lesson.title
        book_title = (lesson.book_title or "").strip() or "Selected textbook"
        book_pages = subsection.display_pages
        day_title = f"Day {day_number}"
        header = [
            f"*📚 {day_title} Lesson (Detailed)*",
            f"Chapter: {chapter}",
            f"Book: {book_title}",
            f"Book Pages: {book_pages}",
            f"Grade: {grade_value}",
            f"Subject: {subject_display}",
            f"Class Duration: {requested_duration} minutes",
            "Resource Profile: Resource-Limited",
            f"⏱ Total lesson time: ~{requested_duration} minutes",
        ]

        lines = (text or "").splitlines()
        section_start = None
        section_header_pattern = re.compile(r"^\*?\s*(⭐|📚\s+Lesson Overview|🎯|🧰|👩‍🏫|📖|👥|✅|🏠)")
        for index, line in enumerate(lines):
            if section_header_pattern.match(line.strip()):
                section_start = index
                break
        body_lines = lines[section_start:] if section_start is not None else []
        body = "\n".join(body_lines).strip()
        if body:
            return "\n".join(header).strip() + "\n\n" + body
        return "\n".join(header).strip()

    def _extract_duration_minutes(self, text: str) -> int | None:
        match = re.search(r"Total lesson time:\s*~?\s*(\d{1,3})\s*minutes", text or "", flags=re.IGNORECASE)
        if not match:
            return None
        try:
            value = int(match.group(1))
        except ValueError:
            return None
        return value if value > 0 else None
