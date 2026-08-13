from __future__ import annotations

import re
from dataclasses import dataclass

from openai import OpenAI
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.language import DEFAULT_LANGUAGE, generation_language_instruction, language_key, normalize_language
from app.core.logging import get_logger, log_event
from app.models.teacher_profile import TeacherProfile
from app.repositories.embedding_content_repository import EmbeddingLessonMatch, EmbeddingSubsection
from app.services.lesson_generation_provider import PromptBundle
from app.services.output_normalizer import normalize_lesson_output
from app.services.whatsapp_formatter import format_whatsapp_lesson
from app.utils.subject_normalization import normalize_subject, subject_display_name
from app.utils.toc_terminology import toc_label

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
        preferred_language: str | None = None,
    ) -> tuple[str, str]:
        active_language = self._resolve_language(preferred_language, teacher)
        prompt = self._section_summary_prompt(
            lesson=lesson,
            teacher=teacher,
            grade=grade,
            subject=subject,
            duration_minutes=duration_minutes,
            preferred_language=active_language,
        )
        self._log_section_db_text(
            lesson=lesson,
            teacher=teacher,
            grade=grade,
            subject=subject,
            duration_minutes=duration_minutes,
        )
        fallback = self._fallback_section_summary(lesson, language=active_language)
        raw_summary, provider_used = self._generate_or_fallback(
            prompt,
            fallback=fallback,
            task="section_summary",
            context={
                "document_id": lesson.document_id,
                "document_key": lesson.document_key,
                "chapter_id": lesson.chapter_id,
                "lesson_title": lesson.title,
                "preferred_language": active_language,
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
            preferred_language=active_language,
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
        preferred_language: str | None = None,
    ) -> PdfContentLessonResult:
        active_language = self._resolve_language(preferred_language, teacher)
        prompt = self._day_lesson_prompt(
            lesson=lesson,
            subsection=subsection,
            day_number=day_number,
            teacher=teacher,
            grade=grade,
            subject=subject,
            duration_minutes=duration_minutes,
            preferred_language=active_language,
        )
        self._log_subsection_db_text(
            lesson=lesson,
            subsection=subsection,
            day_number=day_number,
            teacher=teacher,
            grade=grade,
            subject=subject,
            duration_minutes=duration_minutes,
        )
        fallback = self._fallback_day_lesson_plan(
            lesson=lesson,
            subsection=subsection,
            day_number=day_number,
            teacher=teacher,
            grade=grade,
            subject=subject,
            duration_minutes=duration_minutes,
            preferred_language=active_language,
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
                "preferred_language": active_language,
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
            preferred_language=active_language,
        )
        duration = (
            duration_minutes
            or self._extract_duration_minutes(whatsapp_lesson_text)
            or self._extract_duration_minutes(normalized_lesson_text)
            or 40
        )
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
            preferred_language=active_language,
            provider_used=provider_used,
            raw_output_length=len(raw_lesson_text),
            normalized_output_length=len(normalized_lesson_text),
            whatsapp_output_length=len(whatsapp_lesson_text),
            raw_llm_output=raw_lesson_text,
            normalized_llm_output=normalized_lesson_text,
            whatsapp_lesson_output=whatsapp_lesson_text,
        )
        return PdfContentLessonResult(
            lesson_text=whatsapp_lesson_text,
            provider_used=provider_used,
            duration_minutes=duration,
        )

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

    def _resolve_language(self, preferred_language: str | None, teacher: TeacherProfile) -> str:
        configured_default = normalize_language(getattr(self.settings, "default_language", None), default=DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE
        teacher_language = getattr(teacher, "preferred_language", None)
        return normalize_language(preferred_language or teacher_language, default=configured_default) or configured_default

    def _source_preservation_instruction(self, preferred_language: str) -> str:
        key = language_key(preferred_language)
        if key == "hindi":
            return (
                "Textbook source content may be in another language. Preserve book titles, TOC item titles, names, formulas, "
                "quoted textbook terms, and exact source identifiers as supplied when you need to reference them. "
                "Do not translate or rewrite the supplied source text itself. All newly generated explanations, bullets, labels, "
                "and section headings must follow the Hindi/Devanagari output rule."
            )
        if key == "hinglish":
            return (
                "Textbook source content may be in another script or language. Preserve book titles, TOC item titles, names, formulas, "
                "quoted textbook terms, and exact source identifiers as supplied when referenced. Do not transliterate or translate the source text itself. "
                "All newly generated explanations and bullets must be simple Roman-script Hinglish."
            )
        return (
            "Preserve book titles, TOC item titles, names, formulas, quoted textbook terms, and exact source identifiers as supplied. "
            "Do not translate or rewrite the supplied source text itself; write newly generated explanations in English."
        )

    def _default_book_title(self, preferred_language: str) -> str:
        key = language_key(preferred_language)
        if key == "hindi":
            return "चुनी हुई पाठ्यपुस्तक"
        if key == "hinglish":
            return "Selected textbook"
        return "Selected textbook"

    def _day_output_labels(self, preferred_language: str, day_number: int, toc_kind: str = "chapter") -> dict[str, str]:
        key = language_key(preferred_language)
        source_label = toc_label(toc_kind, preferred_language)
        if key == "hindi":
            return {
                "day_title": f"दिन {day_number}",
                "lesson_title": f"📚 दिन {day_number} पाठ (विस्तृत)",
                "chapter": source_label,
                "book": "पुस्तक",
                "book_pages": "पुस्तक पृष्ठ",
                "grade": "ग्रेड/कक्षा",
                "subject": "विषय",
                "class_duration": "कक्षा अवधि",
                "minutes": "मिनट",
                "resource_profile": "संसाधन प्रोफ़ाइल",
                "resource_limited": "सीमित संसाधन",
                "total_time": "कुल पाठ समय",
                "teacher_quick_view": "⭐ शिक्षक त्वरित दृश्य",
                "lesson_overview": "📚 पाठ अवलोकन",
                "learning_goal": "🎯 सीखने का लक्ष्य",
                "materials_needed": "🧰 आवश्यक सामग्री",
                "teacher_explanation": "👩‍🏫 शिक्षक व्याख्या",
                "book_connection": "📖 पुस्तक से संबंध",
                "student_activity": "👥 विद्यार्थी गतिविधि",
                "check_understanding": "✅ समझ की जाँच",
                "homework": "🏠 गृहकार्य",
            }
        # Hinglish intentionally keeps short structural labels in English, matching
        # the existing generic PromptBuilder, while all generated explanatory text
        # is Roman-script Hinglish.
        return {
            "day_title": f"Day {day_number}",
            "lesson_title": f"📚 Day {day_number} Lesson (Detailed)",
            "chapter": source_label,
            "book": "Book",
            "book_pages": "Book Pages",
            "grade": "Grade",
            "subject": "Subject",
            "class_duration": "Class Duration",
            "minutes": "minutes",
            "resource_profile": "Resource Profile",
            "resource_limited": "Resource-Limited",
            "total_time": "Total lesson time",
            "teacher_quick_view": "⭐ Teacher Quick View",
            "lesson_overview": "📚 Lesson Overview",
            "learning_goal": "🎯 Learning Goal",
            "materials_needed": "🧰 Materials Needed",
            "teacher_explanation": "👩‍🏫 Teacher Explanation",
            "book_connection": "📖 Book Connection",
            "student_activity": "👥 Student Activity",
            "check_understanding": "✅ Check Understanding",
            "homework": "🏠 Homework",
        }

    def _section_summary_prompt(
        self,
        *,
        lesson: EmbeddingLessonMatch,
        teacher: TeacherProfile,
        grade: str | None = None,
        subject: str | None = None,
        duration_minutes: int | None = None,
        preferred_language: str | None = None,
    ) -> PromptBundle:
        active_language = self._resolve_language(preferred_language, teacher)
        lesson_text = self._safe_lesson_text(lesson.text)
        grade_value = grade or lesson.grade or lesson.class_name or teacher.default_grade
        subject_value = subject_display_name(
            normalize_subject(subject or lesson.subject or teacher.default_subject),
            language=active_language,
        )
        language_instruction = generation_language_instruction(active_language, preserve_source_text=True)
        source_instruction = self._source_preservation_instruction(active_language)
        item_label = toc_label(lesson.toc_kind, active_language)
        system_prompt = (
            "You are a helpful teaching assistant for resource-limited classrooms. "
            "You summarize the exact selected textbook TOC item for a teacher before they choose a day. "
            f"{language_instruction} {source_instruction}"
        )
        user_prompt = (
            "Generate a simple summary of the selected textbook TOC item for the teacher.\n\n"
            f"Preferred Language: {active_language}\n"
            f"School: {getattr(teacher, 'school_name', '') or lesson.school_name or ''}\n"
            f"Grade: {grade_value}\n"
            f"Subject: {subject_value}\n"
            f"Class Duration: {duration_minutes or 0} minutes\n"
            f"Book: {lesson.book_title or ''}\n"
            f"{item_label}: {lesson.title}\n"
            f"Book pages: {lesson.display_pages}\n\n"
            "Rules:\n"
            "- Use ONLY the supplied selected TOC-item content.\n"
            f"- {language_instruction}\n"
            f"- {source_instruction}\n"
            "- Keep it WhatsApp friendly.\n"
            "- Do not create a lesson plan yet.\n"
            "- Write exactly 5 to 7 short bullets in the requested profile language.\n"
            "- Mention the main idea, important vocabulary/concepts, and what students will practice.\n"
            "- Do not add a heading, preface, source block, or closing note; return only the bullets.\n"
            "- No markdown tables. No HTML. No LaTeX.\n\n"
            "--- SELECTED BOOK TOC ITEM CONTENT START ---\n"
            f"{lesson_text}\n"
            "--- SELECTED BOOK TOC ITEM CONTENT END ---"
        )
        return PromptBundle(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            metadata={
                "task": "section_summary",
                "grade": grade_value,
                "subject": subject_value,
                "duration_minutes": duration_minutes,
                "preferred_language": active_language,
            },
        )

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
        preferred_language: str | None = None,
    ) -> PromptBundle:
        active_language = self._resolve_language(preferred_language, teacher)
        labels = self._day_output_labels(active_language, day_number, lesson.toc_kind)
        subject_normalized = normalize_subject(subject or lesson.subject or teacher.default_subject)
        subject_display = subject_display_name(subject_normalized, language=active_language)
        grade_value = grade or lesson.grade or lesson.class_name or teacher.default_grade
        requested_duration = int(duration_minutes or 40)
        chapter = lesson.title
        book_title = (lesson.book_title or "").strip() or self._default_book_title(active_language)
        book_pages = subsection.display_pages
        day_content = subsection.text.strip()
        language_instruction = generation_language_instruction(active_language, preserve_source_text=True)
        source_instruction = self._source_preservation_instruction(active_language)

        system_prompt = (
            "You are generating a DETAILED LESSON PLAN for ONE DAY only. "
            f"{language_instruction} {source_instruction}"
        )
        user_prompt = (
            "You are generating a DETAILED LESSON PLAN for ONE DAY only.\n\n"
            f"Preferred Language: {active_language}\n"
            f"This is {labels['day_title']}.\n\n"
            f"{labels['grade']}: {grade_value}\n"
            f"{labels['subject']}: {subject_display}\n"
            f"{labels['chapter']}: {chapter}\n"
            f"{labels['book']}: {book_title}\n"
            f"{labels['class_duration']}: {requested_duration} {labels['minutes']}\n"
            f"{labels['resource_profile']}: {labels['resource_limited']}\n"
            "Format Profile: Detailed\n\n"
            f"OUTPUT LANGUAGE RULE: {language_instruction}\n"
            f"SOURCE PRESERVATION RULE: {source_instruction}\n\n"
            "Use ONLY the supplied DAY content.\n"
            "Do NOT use other book content.\n"
            "Do NOT use content from previous days.\n"
            "Do NOT use content from later days.\n"
            "Do NOT generate a multi-part book summary.\n"
            "Do NOT generate a multi-day plan.\n\n"
            "Base the lesson only on:\n"
            "- supplied DAY content\n"
            "- supplied book page range\n\n"
            f"{labels['book_pages']}:\n"
            f"{book_pages}\n\n"
            "Required output format (use these section headers and metadata labels exactly):\n"
            f"{labels['lesson_title']}\n"
            f"{labels['chapter']}: {chapter}\n"
            f"{labels['book']}: {book_title}\n"
            f"{labels['book_pages']}: {book_pages}\n"
            f"{labels['grade']}: {grade_value}\n"
            f"{labels['subject']}: {subject_display}\n"
            f"{labels['class_duration']}: {requested_duration} {labels['minutes']}\n"
            f"{labels['resource_profile']}: {labels['resource_limited']}\n"
            f"⏱ {labels['total_time']}: ~{requested_duration} {labels['minutes']}\n\n"
            f"{labels['teacher_quick_view']}\n\n"
            f"{labels['lesson_overview']}\n\n"
            f"{labels['learning_goal']}\n\n"
            f"{labels['materials_needed']}\n\n"
            f"{labels['teacher_explanation']}\n\n"
            f"{labels['book_connection']}\n\n"
            f"{labels['student_activity']}\n\n"
            f"{labels['check_understanding']}\n\n"
            f"{labels['homework']}\n\n"
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
            f"- End the response immediately after the {labels['homework']} section.\n"
            "- Do not add any final note, summary, conclusion, or closing sentence after Homework.\n\n"
            f"--- DAY {day_number} CONTENT START ---\n"
            f"{day_content}\n"
            f"--- DAY {day_number} CONTENT END ---"
        )
        return PromptBundle(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            metadata={
                "task": "day_lesson_plan",
                "grade": grade_value,
                "subject": subject_display,
                "chapter": chapter,
                "book_title": book_title,
                "day_number": day_number,
                "book_pages": book_pages,
                "duration_minutes": requested_duration,
                "preferred_language": active_language,
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
        preview = text[:500].strip()
        if preview and len(text) > 500:
            preview += "..."
        lang = language_key(language)
        subsection_count = int(lesson.subsection_count or 0)
        item_label = toc_label(lesson.toc_kind, language)
        if lang == "hindi":
            excerpt = preview or "चुने हुए पुस्तक भाग का पाठ उपलब्ध नहीं है।"
            return (
                f"- यह सारांश चुनी हुई पुस्तक सामग्री पर आधारित है।\n"
                f"- {item_label}: {lesson.title}\n"
                f"- पुस्तक पृष्ठ: {lesson.display_pages}\n"
                f"- इस चुने हुए भाग में {subsection_count} दिन/उपखंड उपलब्ध हैं।\n"
                f"- मूल पाठ का छोटा अंश: {excerpt}"
            )
        if lang == "hinglish":
            excerpt = preview or "Selected book content empty hai."
            return (
                f"- Yeh summary selected book content par based hai.\n"
                f"- {item_label}: {lesson.title}\n"
                f"- Book Pages: {lesson.display_pages}\n"
                f"- Is selected item mein {subsection_count} day/subsection available hain.\n"
                f"- Original textbook ka short excerpt: {excerpt}"
            )
        excerpt = preview or "The selected book content is empty."
        return (
            f"- This summary is based on the selected book content.\n"
            f"- {item_label}: {lesson.title}\n"
            f"- Book Pages: {lesson.display_pages}\n"
            f"- This selected item has {subsection_count} available day/subsection entries.\n"
            f"- Short excerpt from the original textbook: {excerpt}"
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
        preferred_language: str | None = None,
    ) -> str:
        active_language = self._resolve_language(preferred_language, teacher)
        labels = self._day_output_labels(active_language, day_number, lesson.toc_kind)
        subject_display = subject_display_name(
            normalize_subject(subject or lesson.subject or teacher.default_subject),
            language=active_language,
        )
        grade_value = grade or lesson.grade or lesson.class_name or teacher.default_grade
        requested_duration = int(duration_minutes or 40)
        chapter = lesson.title
        book_title = (lesson.book_title or "").strip() or self._default_book_title(active_language)
        book_pages = subsection.display_pages
        header = (
            f"{labels['lesson_title']}\n"
            f"{labels['chapter']}: {chapter}\n"
            f"{labels['book']}: {book_title}\n"
            f"{labels['book_pages']}: {book_pages}\n"
            f"{labels['grade']}: {grade_value}\n"
            f"{labels['subject']}: {subject_display}\n"
            f"{labels['class_duration']}: {requested_duration} {labels['minutes']}\n"
            f"{labels['resource_profile']}: {labels['resource_limited']}\n"
            f"⏱ {labels['total_time']}: ~{requested_duration} {labels['minutes']}\n\n"
        )
        lang = language_key(active_language)
        if lang == "hindi":
            return header + (
                f"{labels['teacher_quick_view']}\n"
                f"{labels['grade']}: {grade_value}\n"
                f"{labels['subject']}: {subject_display}\n"
                f"{labels['class_duration']}: {requested_duration} {labels['minutes']}\n"
                f"केवल दिन {day_number} की दी गई पाठ्यपुस्तक सामग्री का उपयोग करें।\n\n"
                f"{labels['lesson_overview']}\n"
                f"विद्यार्थी {chapter} के चुने हुए भाग का अध्ययन करेंगे।\n"
                "शिक्षक व्याख्या को सीधे पुस्तक की पंक्तियों और गतिविधियों से जोड़ेंगे।\n\n"
                f"{labels['learning_goal']}\n"
                "विद्यार्थी दिए गए दिन की सामग्री का मुख्य विचार समझेंगे।\n"
                "विद्यार्थी चुने हुए पुस्तक पृष्ठों से छोटे मौखिक या लिखित प्रश्नों के उत्तर देंगे।\n\n"
                f"{labels['materials_needed']}\n"
                "पाठ्यपुस्तक।\n"
                "ब्लैकबोर्ड या कॉपी।\n"
                "चॉक या पेंसिल।\n\n"
                f"{labels['teacher_explanation']}\n"
                "चुनी हुई पुस्तक सामग्री को ज़ोर से पढ़ें।\n"
                "महत्वपूर्ण पंक्तियों के बाद रुकें।\n"
                "कठिन शब्दों या चरणों को सरल हिंदी में समझाएँ।\n\n"
                f"{labels['book_connection']}\n"
                f"विद्यार्थियों से पुस्तक पृष्ठ {book_pages} देखने को कहें।\n"
                "उदाहरण और प्रश्न केवल इन्हीं पृष्ठों से लें।\n\n"
                f"{labels['student_activity']}\n"
                "विद्यार्थी जोड़ों में काम करें।\n"
                "हर जोड़ी दिन की सामग्री से दो महत्वपूर्ण बिंदु चुने।\n"
                "कुछ विद्यार्थी अपने उत्तर पूरी कक्षा के साथ साझा करें।\n\n"
                f"{labels['check_understanding']}\n"
                "दी गई सामग्री से दो छोटे प्रश्न पूछें।\n"
                "एक विद्यार्थी से मुख्य विचार एक वाक्य में समझाने को कहें।\n\n"
                f"{labels['homework']}\n"
                "चुने हुए पुस्तक पृष्ठ दोहराएँ।\n"
                "आज आपने क्या समझा, उस पर तीन पंक्तियाँ लिखें।"
            )
        if lang == "hinglish":
            return header + (
                f"{labels['teacher_quick_view']}\n"
                f"Grade: {grade_value}\n"
                f"Subject: {subject_display}\n"
                f"Class Duration: {requested_duration} minutes\n"
                f"Sirf Day {day_number} ke diye gaye textbook content ka use karein.\n\n"
                f"{labels['lesson_overview']}\n"
                f"Students {chapter} ke selected part ko padhenge.\n"
                "Teacher explanation ko directly book ki lines aur activities se connect karein.\n\n"
                f"{labels['learning_goal']}\n"
                "Students supplied day content ka main idea samjhenge.\n"
                "Students selected book pages se short oral ya written questions answer karenge.\n\n"
                f"{labels['materials_needed']}\n"
                "Textbook.\n"
                "Blackboard ya notebook.\n"
                "Chalk ya pencil.\n\n"
                f"{labels['teacher_explanation']}\n"
                "Selected book content ko aloud padhein.\n"
                "Important lines ke baad pause karein.\n"
                "Difficult words ya steps ko simple Hinglish mein samjhayen.\n\n"
                f"{labels['book_connection']}\n"
                f"Students ko book pages {book_pages} dekhne ko kahen.\n"
                "Examples aur questions sirf in pages se lein.\n\n"
                f"{labels['student_activity']}\n"
                "Students pairs mein kaam karein.\n"
                "Har pair day content se do important points nikale.\n"
                "Kuch students apne answers class ke saath share karein.\n\n"
                f"{labels['check_understanding']}\n"
                "Supplied content se do short questions poochhein.\n"
                "Ek student se main idea ek sentence mein explain karne ko kahen.\n\n"
                f"{labels['homework']}\n"
                "Selected book pages revise karein.\n"
                "Aaj kya samjha us par teen lines likhein."
            )
        return header + (
            f"{labels['teacher_quick_view']}\n"
            f"Grade: {grade_value}\n"
            f"Subject: {subject_display}\n"
            f"Class Duration: {requested_duration} minutes\n"
            f"Use only Day {day_number} textbook content.\n\n"
            f"{labels['lesson_overview']}\n"
            f"Students will study the selected part of {chapter}.\n"
            "The teacher should connect explanation directly to the book lines and activities.\n\n"
            f"{labels['learning_goal']}\n"
            "Students will understand the main idea from the supplied day content.\n"
            "Students will answer short oral or written questions from the book pages.\n\n"
            f"{labels['materials_needed']}\n"
            "Textbook.\n"
            "Blackboard or notebook.\n"
            "Chalk or pencil.\n\n"
            f"{labels['teacher_explanation']}\n"
            "Read the selected book content aloud.\n"
            "Pause after important lines.\n"
            "Explain difficult words or steps in simple language.\n\n"
            f"{labels['book_connection']}\n"
            f"Ask students to look at book pages {book_pages}.\n"
            "Use examples and questions only from these pages.\n\n"
            f"{labels['student_activity']}\n"
            "Students work in pairs.\n"
            "Each pair finds two important points from the day content.\n"
            "A few students share answers with the class.\n\n"
            f"{labels['check_understanding']}\n"
            "Ask two short questions from the supplied content.\n"
            "Ask one student to explain the main idea in one sentence.\n\n"
            f"{labels['homework']}\n"
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
        preferred_language: str | None = None,
    ) -> str:
        """Ensure the visible lesson starts with profile-language metadata."""
        active_language = self._resolve_language(preferred_language, teacher)
        labels = self._day_output_labels(active_language, day_number, lesson.toc_kind)
        subject_display = subject_display_name(
            normalize_subject(subject or lesson.subject or teacher.default_subject),
            language=active_language,
        )
        grade_value = grade or lesson.grade or lesson.class_name or teacher.default_grade
        requested_duration = int(duration_minutes or self._extract_duration_minutes(text) or 40)
        chapter = lesson.title
        book_title = (lesson.book_title or "").strip() or self._default_book_title(active_language)
        book_pages = subsection.display_pages
        header = [
            f"*{labels['lesson_title']}*",
            f"{labels['chapter']}: {chapter}",
            f"{labels['book']}: {book_title}",
            f"{labels['book_pages']}: {book_pages}",
            f"{labels['grade']}: {grade_value}",
            f"{labels['subject']}: {subject_display}",
            f"{labels['class_duration']}: {requested_duration} {labels['minutes']}",
            f"{labels['resource_profile']}: {labels['resource_limited']}",
            f"⏱ {labels['total_time']}: ~{requested_duration} {labels['minutes']}",
        ]

        lines = (text or "").splitlines()
        section_start = None
        # Every required section starts with one of these emojis in every profile
        # language, so this remains language-independent.
        section_header_pattern = re.compile(r"^\*?\s*(⭐|📚|🎯|🧰|👩‍🏫|📖|👥|✅|🏠)")
        for index, line in enumerate(lines):
            stripped = line.strip()
            if section_header_pattern.match(stripped) and index > 0:
                # Skip the top lesson title (also starts with 📚); start at the
                # first real content section.
                if "Lesson (Detailed)" in stripped or "पाठ (विस्तृत)" in stripped:
                    continue
                section_start = index
                break
        body_lines = lines[section_start:] if section_start is not None else []
        body = "\n".join(body_lines).strip()
        if body:
            return "\n".join(header).strip() + "\n\n" + body
        return "\n".join(header).strip()

    def _extract_duration_minutes(self, text: str) -> int | None:
        patterns = [
            r"Total lesson time:\s*~?\s*(\d{1,3})\s*minutes",
            r"Class Duration:\s*~?\s*(\d{1,3})\s*minutes",
            r"कुल पाठ समय:\s*~?\s*(\d{1,3})\s*मिनट",
            r"कक्षा अवधि:\s*~?\s*(\d{1,3})\s*मिनट",
        ]
        match = None
        for pattern in patterns:
            match = re.search(pattern, text or "", flags=re.IGNORECASE)
            if match:
                break
        if not match:
            return None
        try:
            value = int(match.group(1))
        except ValueError:
            return None
        return value if value > 0 else None

