from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger, log_event
from app.utils.subject_normalization import normalize_subject
from app.utils.toc_terminology import infer_toc_kind

logger = get_logger(__name__)


_TOPIC_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is", "it",
    "of", "on", "or", "the", "to", "with", "without", "about", "after", "before", "over", "under",
    "this", "that", "these", "those", "lesson", "chapter", "topic", "class", "grade", "subject", "unit",
}


@dataclass(slots=True)
class EmbeddingLessonMatch:
    document_id: str
    chapter_id: str
    document_key: str | None
    school_name: str | None
    grade: str | None
    class_name: str | None
    subject: str | None
    book_title: str | None
    chapter_number: str | None
    chapter_title: str | None
    unit_number: str | None
    unit_title: str | None
    section_number: str | None
    section_title: str | None
    lesson_title: str | None
    structure_type: str | None
    pdf_start_page: int | None
    pdf_end_page: int | None
    printed_start_page: str | None
    printed_end_page: str | None
    text: str
    subsection_count: int = 0
    match_score: int = 0

    @property
    def toc_kind(self) -> str:
        return infer_toc_kind(
            structure_type=self.structure_type,
            chapter_title=self.chapter_title,
            unit_title=self.unit_title,
            section_title=self.section_title,
            lesson_title=self.lesson_title,
        )

    @property
    def title(self) -> str:
        if self.toc_kind == "chapter":
            candidates = (self.chapter_title, self.section_title, self.lesson_title, self.unit_title)
        elif self.toc_kind == "lesson":
            candidates = (self.lesson_title, self.section_title, self.chapter_title, self.unit_title)
        elif self.toc_kind == "section":
            candidates = (self.section_title, self.lesson_title, self.chapter_title, self.unit_title)
        elif self.toc_kind == "unit":
            candidates = (self.unit_title, self.section_title, self.chapter_title, self.lesson_title)
        else:
            candidates = (self.section_title, self.lesson_title, self.chapter_title, self.unit_title)
        return next((str(value).strip() for value in candidates if str(value or "").strip()), self.book_title or "Selected lesson").strip()

    @property
    def toc_number(self) -> str | None:
        if self.toc_kind == "chapter":
            return self.chapter_number or self.section_number or self.unit_number
        if self.toc_kind == "lesson":
            return self.section_number or self.chapter_number or self.unit_number
        if self.toc_kind == "section":
            return self.section_number or self.chapter_number or self.unit_number
        if self.toc_kind == "unit":
            return self.unit_number or self.section_number or self.chapter_number
        return self.section_number or self.chapter_number or self.unit_number

    @property
    def display_pages(self) -> str:
        # Teacher-facing page references are always printed/book pages. Physical
        # PDF coordinates remain internal database/retrieval metadata only.
        if self.printed_start_page and self.printed_end_page:
            return f"{self.printed_start_page}-{self.printed_end_page}"
        return "Not available"


@dataclass(slots=True)
class EmbeddingSubsection:
    id: str
    document_id: str
    subsection_number: str | None
    subsection_title: str | None
    anchor_marker: str | None
    pdf_start_page: int | None
    pdf_end_page: int | None
    printed_start_page: str | None
    printed_end_page: str | None
    page_numbers: list[int]
    printed_page_numbers: list[int]
    includes: list[str]
    text: str
    text_length_chars: int | None
    include_in_embeddings: bool | None
    embedding_readiness: str | None
    quality_flags: list[str]
    display_page_override: str | None = None
    source_kind: str | None = None
    schedule_week_start_date: str | None = None
    schedule_exercise: str | None = None
    schedule_questions: list[str] | None = None
    schedule_topic: str | None = None
    schedule_activity: str | None = None

    @property
    def title(self) -> str:
        return (self.subsection_title or self.anchor_marker or self.subsection_number or "Day").strip()

    @property
    def display_pages(self) -> str:
        if (self.display_page_override or "").strip():
            return str(self.display_page_override).strip()
        if self.printed_start_page and self.printed_end_page:
            if str(self.printed_start_page) == str(self.printed_end_page):
                return str(self.printed_start_page)
            return f"{self.printed_start_page}-{self.printed_end_page}"

        # Older/incompletely migrated embeddings rows may have the printed
        # page list even when the explicit printed start/end columns are null.
        labels = [str(value).strip() for value in self.printed_page_numbers if str(value).strip()]
        if labels:
            if labels[0] == labels[-1]:
                return labels[0]
            return f"{labels[0]}-{labels[-1]}"
        return "Not available"


@dataclass(slots=True)
class EmbeddingTeacherSchedule:
    id: str
    document_id: str
    schedule_key: str | None
    chapter_number: str | None
    chapter_title: str | None
    section_number: str | None
    section_title: str | None
    week_start_date: str | None
    schedule_source: str | None
    schedule_type: str | None
    exercise: str | None
    schedule_note: str | None
    day_count: int = 0


@dataclass(slots=True)
class EmbeddingTeacherScheduleDay:
    id: str
    teacher_schedule_id: str
    document_id: str
    day: int | None
    weekday: str | None
    day_type: str | None
    activity: str | None
    topic: str | None
    teaching_book_page_ranges: list[dict[str, Any]]
    exercise_book_pages: list[int]
    exercise: str | None
    questions: list[str]
    range_source: str | None
    source_input_warning: str | None
    selected_book_pages: list[int]
    selected_pdf_pages: list[int]
    selected_page_count: int | None
    selection_is_contiguous: bool | None
    display_book_pages: str | None
    display_pdf_pages: str | None
    selection_policy: str | None
    selected_pages_available: bool | None

    @property
    def display_pages(self) -> str:
        if self.selected_book_pages:
            return EmbeddingContentRepository.format_book_page_sequence(self.selected_book_pages)
        return (self.display_book_pages or "").strip() or "Not available"

    @property
    def questions_display(self) -> str:
        return ", ".join(str(item).strip() for item in self.questions if str(item).strip())


@dataclass(slots=True)
class EmbeddingPageExtraction:
    pdf_page_number: int
    printed_page_number: str | None
    printed_page_label: str | None
    text: str
    include_in_lesson_text: bool | None = None
    include_in_embeddings: bool | None = None
    quality_flags: list[str] | None = None

    @property
    def book_page_label(self) -> str | None:
        value = (self.printed_page_number or "").strip() or (self.printed_page_label or "").strip()
        return value or None

    @property
    def display_page(self) -> str:
        # Never expose the physical PDF coordinate to the teacher.
        return self.book_page_label or "Not available"


class EmbeddingContentRepository:
    """Read-only access to the pdf_to_embeddings tables in the same database."""

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    @property
    def _schema_prefix(self) -> str:
        return "" if self.settings.database_is_sqlite else "public."

    def list_schools(self) -> list[str]:
        sql = text(
            f"""
            SELECT DISTINCT school_name
            FROM {self._schema_prefix}embeddings_documents
            WHERE school_name IS NOT NULL
              AND trim(school_name) <> ''
            ORDER BY school_name
            """
        )
        try:
            rows = self.db.execute(sql).mappings().all()
        except SQLAlchemyError as exc:
            log_event(logger, "embedding_schools_lookup_failed", error=str(exc))
            self.db.rollback()
            return []

        schools = [str(row["school_name"]).strip() for row in rows if str(row.get("school_name") or "").strip()]
        log_event(logger, "embedding_schools_lookup", count=len(schools))
        return schools

    def get_school_by_index(self, index: int) -> str | None:
        schools = self.list_schools()
        if 1 <= index <= len(schools):
            return schools[index - 1]
        return None

    def resolve_school_choice(self, value: str) -> str | None:
        raw = (value or "").strip()
        if not raw:
            return None
        normalized = raw.casefold()
        if normalized.startswith("school:"):
            raw_index = normalized.split(":", 1)[1].strip()
            if raw_index.isdigit():
                return self.get_school_by_index(int(raw_index))
        if raw.isdigit():
            return self.get_school_by_index(int(raw))

        schools = self.list_schools()
        exact = next((school for school in schools if school.casefold() == normalized), None)
        if exact:
            return exact
        prefix_matches = [school for school in schools if school.casefold().startswith(normalized)]
        if len(prefix_matches) == 1:
            return prefix_matches[0]
        return None

    def find_lesson_match(
        self,
        *,
        school_name: str | None,
        grade: str | None,
        subject: str | None,
        topic: str,
    ) -> EmbeddingLessonMatch | None:
        candidates = self._candidate_lessons(school_name=school_name, grade=grade, subject=subject)
        if not candidates:
            return None

        topic_norm = self._normalize_title(topic)
        topic_tokens = set(self._tokens(topic))
        scored: list[EmbeddingLessonMatch] = []
        for item in candidates:
            title_candidates = [item.section_title, item.lesson_title, item.chapter_title]
            best_score = 0
            for candidate_title in title_candidates:
                score = self._title_score(topic_norm, topic_tokens, candidate_title)
                best_score = max(best_score, score)
            if best_score <= 0:
                continue
            item.match_score = best_score
            scored.append(item)

        if not scored:
            log_event(
                logger,
                "embedding_lesson_match_not_found",
                topic=topic,
                school_name=school_name,
                grade=grade,
                subject=subject,
                candidate_count=len(candidates),
            )
            return None

        scored.sort(
            key=lambda row: (
                row.match_score,
                row.subsection_count,
                -(row.pdf_start_page or 999999),
            ),
            reverse=True,
        )
        best = scored[0]
        log_event(
            logger,
            "embedding_lesson_match_found",
            topic=topic,
            match_title=best.title,
            match_score=best.match_score,
            document_key=best.document_key,
            chapter_id=best.chapter_id,
            subsection_count=best.subsection_count,
        )
        return best

    def get_lesson_by_chapter_id(self, chapter_id: str) -> EmbeddingLessonMatch | None:
        rows = self._candidate_lessons(chapter_id=chapter_id)
        return rows[0] if rows else None

    @staticmethod
    def format_book_page_sequence(values: list[int]) -> str:
        """Compact an exact page selection without pretending gaps are contiguous."""
        normalized = sorted({int(value) for value in values if value is not None})
        if not normalized:
            return "Not available"
        parts: list[str] = []
        start = previous = normalized[0]
        for value in normalized[1:]:
            if value == previous + 1:
                previous = value
                continue
            parts.append(str(start) if start == previous else f"{start}-{previous}")
            start = previous = value
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        return ", ".join(parts)

    def list_teacher_schedules_for_lesson(self, lesson: EmbeddingLessonMatch) -> list[EmbeddingTeacherSchedule]:
        """Return optional real-teacher schedules for a selected TOC item.

        These tables are additive. If they do not exist yet, or no schedule was
        ingested for this book/chapter, return an empty list so callers can use
        the existing structural subsection/day flow unchanged.
        """
        if not lesson.document_id:
            return []

        id_select = "CAST(ts.id AS text)" if not self.settings.database_is_sqlite else "CAST(ts.id AS TEXT)"
        doc_select = "CAST(ts.document_id AS text)" if not self.settings.database_is_sqlite else "CAST(ts.document_id AS TEXT)"
        document_expr = "CAST(:document_id AS uuid)" if not self.settings.database_is_sqlite else ":document_id"
        sql = text(
            f"""
            SELECT
                {id_select} AS id,
                {doc_select} AS document_id,
                ts.schedule_key,
                ts.chapter_number,
                ts.chapter_title,
                ts.section_number,
                ts.section_title,
                ts.week_start_date,
                ts.schedule_source,
                ts.schedule_type,
                ts.exercise,
                ts.schedule_note,
                (
                    SELECT COUNT(*)
                    FROM {self._schema_prefix}embeddings_teacher_schedule_days td
                    WHERE td.teacher_schedule_id = ts.id
                ) AS day_count
            FROM {self._schema_prefix}embeddings_teacher_schedules ts
            WHERE ts.document_id = {document_expr}
            ORDER BY ts.week_start_date, ts.exercise, ts.schedule_key
            """
        )
        try:
            rows = self.db.execute(sql, {"document_id": lesson.document_id}).mappings().all()
        except SQLAlchemyError as exc:
            # Old databases and books intentionally fall back to structural days.
            log_event(
                logger,
                "embedding_teacher_schedules_lookup_unavailable",
                error=str(exc),
                document_id=lesson.document_id,
                chapter_id=lesson.chapter_id,
            )
            self.db.rollback()
            return []

        schedules = [self._teacher_schedule_from_row(row) for row in rows]
        matched = [item for item in schedules if self._teacher_schedule_matches_lesson(item, lesson)]
        log_event(
            logger,
            "embedding_teacher_schedules_lookup",
            document_id=lesson.document_id,
            chapter_id=lesson.chapter_id,
            count=len(matched),
        )
        return matched

    def get_teacher_schedule_by_id(self, schedule_id: str) -> EmbeddingTeacherSchedule | None:
        if not schedule_id:
            return None
        id_select = "CAST(ts.id AS text)" if not self.settings.database_is_sqlite else "CAST(ts.id AS TEXT)"
        doc_select = "CAST(ts.document_id AS text)" if not self.settings.database_is_sqlite else "CAST(ts.document_id AS TEXT)"
        id_expr = "CAST(:schedule_id AS uuid)" if not self.settings.database_is_sqlite else ":schedule_id"
        sql = text(
            f"""
            SELECT
                {id_select} AS id,
                {doc_select} AS document_id,
                ts.schedule_key,
                ts.chapter_number,
                ts.chapter_title,
                ts.section_number,
                ts.section_title,
                ts.week_start_date,
                ts.schedule_source,
                ts.schedule_type,
                ts.exercise,
                ts.schedule_note,
                (
                    SELECT COUNT(*)
                    FROM {self._schema_prefix}embeddings_teacher_schedule_days td
                    WHERE td.teacher_schedule_id = ts.id
                ) AS day_count
            FROM {self._schema_prefix}embeddings_teacher_schedules ts
            WHERE ts.id = {id_expr}
            LIMIT 1
            """
        )
        try:
            row = self.db.execute(sql, {"schedule_id": schedule_id}).mappings().first()
        except SQLAlchemyError as exc:
            log_event(logger, "embedding_teacher_schedule_lookup_failed", error=str(exc), schedule_id=schedule_id)
            self.db.rollback()
            return None
        return self._teacher_schedule_from_row(row) if row else None

    def list_teacher_schedule_days(self, schedule_id: str) -> list[EmbeddingTeacherScheduleDay]:
        if not schedule_id:
            return []
        id_select = "CAST(td.id AS text)" if not self.settings.database_is_sqlite else "CAST(td.id AS TEXT)"
        schedule_select = "CAST(td.teacher_schedule_id AS text)" if not self.settings.database_is_sqlite else "CAST(td.teacher_schedule_id AS TEXT)"
        doc_select = "CAST(td.document_id AS text)" if not self.settings.database_is_sqlite else "CAST(td.document_id AS TEXT)"
        schedule_expr = "CAST(:schedule_id AS uuid)" if not self.settings.database_is_sqlite else ":schedule_id"
        sql = text(
            f"""
            SELECT
                {id_select} AS id,
                {schedule_select} AS teacher_schedule_id,
                {doc_select} AS document_id,
                td.day,
                td.weekday,
                td.day_type,
                td.activity,
                td.topic,
                td.teaching_book_page_ranges,
                td.exercise_book_pages,
                td.exercise,
                td.questions,
                td.range_source,
                td.source_input_warning,
                td.selected_book_pages,
                td.selected_pdf_pages,
                td.selected_page_count,
                td.selection_is_contiguous,
                td.display_book_pages,
                td.display_pdf_pages,
                td.selection_policy,
                td.selected_pages_available
            FROM {self._schema_prefix}embeddings_teacher_schedule_days td
            WHERE td.teacher_schedule_id = {schedule_expr}
            ORDER BY COALESCE(td.day, 2147483647), td.weekday
            """
        )
        try:
            rows = self.db.execute(sql, {"schedule_id": schedule_id}).mappings().all()
        except SQLAlchemyError as exc:
            log_event(logger, "embedding_teacher_schedule_days_lookup_failed", error=str(exc), schedule_id=schedule_id)
            self.db.rollback()
            return []
        return [self._teacher_schedule_day_from_row(row) for row in rows]

    def get_teacher_schedule_day_by_id(self, day_id: str) -> EmbeddingTeacherScheduleDay | None:
        if not day_id:
            return None
        id_select = "CAST(td.id AS text)" if not self.settings.database_is_sqlite else "CAST(td.id AS TEXT)"
        schedule_select = "CAST(td.teacher_schedule_id AS text)" if not self.settings.database_is_sqlite else "CAST(td.teacher_schedule_id AS TEXT)"
        doc_select = "CAST(td.document_id AS text)" if not self.settings.database_is_sqlite else "CAST(td.document_id AS TEXT)"
        id_expr = "CAST(:day_id AS uuid)" if not self.settings.database_is_sqlite else ":day_id"
        sql = text(
            f"""
            SELECT
                {id_select} AS id,
                {schedule_select} AS teacher_schedule_id,
                {doc_select} AS document_id,
                td.day,
                td.weekday,
                td.day_type,
                td.activity,
                td.topic,
                td.teaching_book_page_ranges,
                td.exercise_book_pages,
                td.exercise,
                td.questions,
                td.range_source,
                td.source_input_warning,
                td.selected_book_pages,
                td.selected_pdf_pages,
                td.selected_page_count,
                td.selection_is_contiguous,
                td.display_book_pages,
                td.display_pdf_pages,
                td.selection_policy,
                td.selected_pages_available
            FROM {self._schema_prefix}embeddings_teacher_schedule_days td
            WHERE td.id = {id_expr}
            LIMIT 1
            """
        )
        try:
            row = self.db.execute(sql, {"day_id": day_id}).mappings().first()
        except SQLAlchemyError as exc:
            log_event(logger, "embedding_teacher_schedule_day_lookup_failed", error=str(exc), day_id=day_id)
            self.db.rollback()
            return None
        return self._teacher_schedule_day_from_row(row) if row else None

    def build_subsection_from_teacher_schedule_day(
        self,
        lesson: EmbeddingLessonMatch,
        schedule: EmbeddingTeacherSchedule,
        schedule_day: EmbeddingTeacherScheduleDay,
    ) -> EmbeddingSubsection | None:
        """Create a lesson-generation source from the schedule's exact page union."""
        pages = self.list_pages_for_lesson(lesson)
        if not pages:
            return None

        selected_pdf_pages = {int(value) for value in schedule_day.selected_pdf_pages if value is not None}
        selected_book_pages = {int(value) for value in schedule_day.selected_book_pages if value is not None}

        selected: list[EmbeddingPageExtraction] = []
        for page in pages:
            if selected_pdf_pages and page.pdf_page_number in selected_pdf_pages:
                selected.append(page)
                continue
            if not selected_pdf_pages and selected_book_pages:
                label = (page.book_page_label or "").strip()
                if label.isdigit() and int(label) in selected_book_pages:
                    selected.append(page)

        # Defensive fallback for older schedule rows that stored only teaching
        # ranges/exercise pages and not the precomputed exact union.
        if not selected and not selected_pdf_pages:
            derived_book_pages: set[int] = set(selected_book_pages)
            for item in schedule_day.teaching_book_page_ranges:
                if not isinstance(item, dict):
                    continue
                start = self._coerce_int(item.get("start_book_page"))
                end = self._coerce_int(item.get("end_book_page"))
                if start is not None and end is not None and start <= end:
                    derived_book_pages.update(range(start, end + 1))
            derived_book_pages.update(schedule_day.exercise_book_pages)
            for page in pages:
                label = (page.book_page_label or "").strip()
                if label.isdigit() and int(label) in derived_book_pages:
                    selected.append(page)

        selected.sort(key=lambda item: item.pdf_page_number)
        if not selected:
            return None

        text_parts = [
            f"Book Page {page.display_page}\n{page.text.strip()}"
            for page in selected
            if page.text and page.text.strip()
        ]
        if not text_parts:
            return None

        exact_book_pages = [
            int(page.book_page_label)
            for page in selected
            if (page.book_page_label or "").strip().isdigit()
        ]
        display_pages = self.format_book_page_sequence(exact_book_pages or schedule_day.selected_book_pages)
        start_label = str(min(exact_book_pages)) if exact_book_pages else None
        end_label = str(max(exact_book_pages)) if exact_book_pages else None
        quality_flags: list[str] = []
        if schedule_day.source_input_warning:
            quality_flags.append("teacher_schedule_source_input_warning")

        return EmbeddingSubsection(
            id=schedule_day.id,
            document_id=lesson.document_id,
            subsection_number=(f"{schedule.exercise or schedule_day.exercise or 'schedule'}:{schedule_day.day}"),
            subsection_title=(schedule_day.activity or schedule_day.weekday or f"Day {schedule_day.day or 1}"),
            anchor_marker=schedule_day.weekday,
            pdf_start_page=min(page.pdf_page_number for page in selected),
            pdf_end_page=max(page.pdf_page_number for page in selected),
            printed_start_page=start_label,
            printed_end_page=end_label,
            page_numbers=[page.pdf_page_number for page in selected],
            printed_page_numbers=exact_book_pages,
            includes=[value for value in (schedule_day.topic, schedule_day.activity) if value],
            text="\n\n".join(text_parts),
            text_length_chars=sum(len(part) for part in text_parts),
            include_in_embeddings=True,
            embedding_readiness="ready",
            quality_flags=quality_flags,
            display_page_override=display_pages,
            source_kind="teacher_schedule_day",
            schedule_week_start_date=schedule.week_start_date,
            schedule_exercise=schedule.exercise or schedule_day.exercise,
            schedule_questions=list(schedule_day.questions or []),
            schedule_topic=schedule_day.topic,
            schedule_activity=schedule_day.activity,
        )

    def list_lessons_for_selection(
        self,
        *,
        school_name: str | None,
        grade: str | None,
        subject: str | None,
    ) -> list[EmbeddingLessonMatch]:
        """Return ordered lessons/sections for the teacher's school + grade + subject.

        This supports the WhatsApp New Lesson flow after the teacher enters grade
        and subject. It mirrors the intended production lookup:
        embeddings_documents.school_name + subject + Class{grade}, ordered by
        numeric section/chapter number.
        """
        lessons = self._candidate_lessons(school_name=school_name, grade=grade, subject=subject)
        if not lessons:
            return []

        section_numbered = [lesson for lesson in lessons if self._is_numeric_lesson_number(lesson.section_number)]
        chapter_numbered = [lesson for lesson in lessons if self._is_numeric_lesson_number(lesson.chapter_number)]
        ordered = section_numbered or chapter_numbered or lessons
        ordered.sort(
            key=lambda lesson: (
                self._numeric_lesson_number(lesson.section_number)
                if self._is_numeric_lesson_number(lesson.section_number)
                else self._numeric_lesson_number(lesson.chapter_number)
                if self._is_numeric_lesson_number(lesson.chapter_number)
                else float("inf"),
                lesson.pdf_start_page or 999999,
                lesson.title.casefold(),
            )
        )
        log_event(
            logger,
            "embedding_lesson_selection_list",
            school_name=school_name,
            grade=grade,
            subject=subject,
            count=len(ordered),
        )
        return ordered

    def list_subsections_for_lesson(self, lesson: EmbeddingLessonMatch) -> list[EmbeddingSubsection]:
        where_parts = ["s.document_id = CAST(:document_id AS uuid)" if not self.settings.database_is_sqlite else "s.document_id = :document_id"]
        params: dict[str, Any] = {"document_id": lesson.document_id}
        if lesson.section_number:
            where_parts.append("s.section_number = :section_number")
            params["section_number"] = lesson.section_number
        elif lesson.chapter_number:
            where_parts.append("s.chapter_number = :chapter_number")
            params["chapter_number"] = lesson.chapter_number
        elif lesson.section_title:
            where_parts.append("lower(s.section_title) = lower(:section_title)")
            params["section_title"] = lesson.section_title
        elif lesson.chapter_title:
            where_parts.append("lower(s.chapter_title) = lower(:chapter_title)")
            params["chapter_title"] = lesson.chapter_title

        sql = text(
            f"""
            SELECT
                CAST(s.id AS text) AS id,
                CAST(s.document_id AS text) AS document_id,
                s.subsection_number,
                s.subsection_title,
                s.anchor_marker,
                s.pdf_start_page,
                s.pdf_end_page,
                s.printed_start_page,
                s.printed_end_page,
                s.page_numbers,
                s.printed_page_numbers,
                s.includes,
                COALESCE(NULLIF(s.subsection_text_plain, ''), s.subsection_text, '') AS text,
                s.text_length_chars,
                s.include_in_embeddings,
                s.embedding_readiness,
                s.quality_flags
            FROM {self._schema_prefix}embeddings_book_subsections s
            WHERE {' AND '.join(where_parts)}
            ORDER BY
                COALESCE(s.pdf_start_page, 999999),
                s.subsection_number,
                s.subsection_title
            """
        )
        if self.settings.database_is_sqlite:
            sql = text(str(sql).replace("CAST(s.id AS text)", "CAST(s.id AS TEXT)").replace("CAST(s.document_id AS text)", "CAST(s.document_id AS TEXT)"))

        try:
            rows = self.db.execute(sql, params).mappings().all()
        except SQLAlchemyError as exc:
            log_event(logger, "embedding_subsections_lookup_failed", error=str(exc), chapter_id=lesson.chapter_id)
            self.db.rollback()
            return []

        subsections = [self._subsection_from_row(row) for row in rows]
        self._hydrate_subsection_book_pages(lesson, subsections)
        return subsections

    def get_subsection_by_id(self, subsection_id: str) -> EmbeddingSubsection | None:
        if not subsection_id:
            return None
        id_expr = "CAST(:subsection_id AS uuid)" if not self.settings.database_is_sqlite else ":subsection_id"
        id_select = "CAST(s.id AS text)" if not self.settings.database_is_sqlite else "CAST(s.id AS TEXT)"
        doc_select = "CAST(s.document_id AS text)" if not self.settings.database_is_sqlite else "CAST(s.document_id AS TEXT)"
        sql = text(
            f"""
            SELECT
                {id_select} AS id,
                {doc_select} AS document_id,
                s.subsection_number,
                s.subsection_title,
                s.anchor_marker,
                s.pdf_start_page,
                s.pdf_end_page,
                s.printed_start_page,
                s.printed_end_page,
                s.page_numbers,
                s.printed_page_numbers,
                s.includes,
                COALESCE(NULLIF(s.subsection_text_plain, ''), s.subsection_text, '') AS text,
                s.text_length_chars,
                s.include_in_embeddings,
                s.embedding_readiness,
                s.quality_flags
            FROM {self._schema_prefix}embeddings_book_subsections s
            WHERE s.id = {id_expr}
            LIMIT 1
            """
        )
        try:
            row = self.db.execute(sql, {"subsection_id": subsection_id}).mappings().first()
        except SQLAlchemyError as exc:
            log_event(logger, "embedding_subsection_lookup_failed", error=str(exc), subsection_id=subsection_id)
            self.db.rollback()
            return None
        if not row:
            return None
        subsection = self._subsection_from_row(row)
        # A selected day is often reloaded by id after the day menu. Older
        # ingestion rows may have null printed_start/end and no printed page
        # list even though page_extractions has the correct book-page labels.
        # Hydrate here as well so the selected object cannot lose the range.
        self._hydrate_single_subsection_book_pages(subsection)
        return subsection

    def list_pages_for_lesson(self, lesson: EmbeddingLessonMatch) -> list[EmbeddingPageExtraction]:
        """Return every physical page inside the selected chapter/section range.

        Page-level customization uses ``embeddings_page_extractions`` as the
        authoritative source. The query is constrained by the selected parent
        record's physical PDF bounds, which prevents a teacher from selecting
        pages from another chapter even when printed labels are unusual.
        """
        if not lesson.document_id or lesson.pdf_start_page is None or lesson.pdf_end_page is None:
            return []

        document_expr = "CAST(:document_id AS uuid)" if not self.settings.database_is_sqlite else ":document_id"
        sql = text(
            f"""
            SELECT
                pe.pdf_page_number,
                pe.printed_page_number,
                pe.printed_page_label,
                COALESCE(
                    NULLIF(pe.production_safe_text, ''),
                    NULLIF(pe.production_page_text, ''),
                    NULLIF(pe.text_plain, ''),
                    NULLIF(pe.text, ''),
                    NULLIF(pe.selectable_text, ''),
                    NULLIF(pe.raw_extracted_text, ''),
                    NULLIF(pe.ocr_text, ''),
                    ''
                ) AS text,
                pe.include_in_lesson_text,
                pe.include_in_embeddings,
                pe.quality_flags
            FROM {self._schema_prefix}embeddings_page_extractions pe
            WHERE pe.document_id = {document_expr}
              AND pe.pdf_page_number BETWEEN :pdf_start_page AND :pdf_end_page
            ORDER BY pe.pdf_page_number
            """
        )
        try:
            rows = self.db.execute(
                sql,
                {
                    "document_id": lesson.document_id,
                    "pdf_start_page": lesson.pdf_start_page,
                    "pdf_end_page": lesson.pdf_end_page,
                },
            ).mappings().all()
        except SQLAlchemyError as exc:
            log_event(
                logger,
                "embedding_chapter_pages_lookup_failed",
                error=str(exc),
                chapter_id=lesson.chapter_id,
                document_id=lesson.document_id,
            )
            self.db.rollback()
            return []

        pages = [
            EmbeddingPageExtraction(
                pdf_page_number=int(row.get("pdf_page_number")),
                printed_page_number=(str(row.get("printed_page_number")).strip() if row.get("printed_page_number") is not None else None),
                printed_page_label=(str(row.get("printed_page_label")).strip() if row.get("printed_page_label") is not None else None),
                text=row.get("text") or "",
                include_in_lesson_text=row.get("include_in_lesson_text"),
                include_in_embeddings=row.get("include_in_embeddings"),
                quality_flags=self._as_list(row.get("quality_flags")),
            )
            for row in rows
        ]
        log_event(
            logger,
            "embedding_chapter_pages_lookup",
            chapter_id=lesson.chapter_id,
            document_id=lesson.document_id,
            pdf_start_page=lesson.pdf_start_page,
            pdf_end_page=lesson.pdf_end_page,
            count=len(pages),
        )
        return pages

    def _hydrate_subsection_book_pages(
        self,
        lesson: EmbeddingLessonMatch,
        subsections: list[EmbeddingSubsection],
    ) -> None:
        """Fill missing day book-page bounds without exposing PDF page numbers.

        Source priority is deliberately teacher-facing only:
        1. explicit subsection printed_start_page / printed_end_page
        2. subsection printed_page_numbers
        3. printed labels from embeddings_page_extractions inside the
           subsection's internal PDF range

        Physical PDF page numbers are used only to locate the page-extraction
        rows; they are never substituted as book-page labels.
        """
        missing = [
            subsection
            for subsection in subsections
            if not subsection.printed_start_page or not subsection.printed_end_page
        ]
        if not missing:
            return

        # First recover from the subsection row itself when the importer stored
        # the list but omitted the explicit start/end columns.
        unresolved: list[EmbeddingSubsection] = []
        for subsection in missing:
            labels = [
                str(value).strip()
                for value in subsection.printed_page_numbers
                if str(value).strip()
            ]
            if labels:
                subsection.printed_start_page = subsection.printed_start_page or labels[0]
                subsection.printed_end_page = subsection.printed_end_page or labels[-1]
            if not subsection.printed_start_page or not subsection.printed_end_page:
                unresolved.append(subsection)

        if not unresolved:
            return

        # Then recover from page-level extraction metadata. Fetch once for the
        # selected TOC item and map each day by its internal PDF bounds.
        pages = self.list_pages_for_lesson(lesson)
        if pages:
            for subsection in unresolved:
                if subsection.pdf_start_page is None or subsection.pdf_end_page is None:
                    continue
                labels = [
                    page.book_page_label
                    for page in pages
                    if subsection.pdf_start_page <= page.pdf_page_number <= subsection.pdf_end_page
                    and page.book_page_label
                ]
                if not labels:
                    continue
                subsection.printed_start_page = subsection.printed_start_page or labels[0]
                subsection.printed_end_page = subsection.printed_end_page or labels[-1]
                if not subsection.printed_page_numbers:
                    subsection.printed_page_numbers = labels

        # Some older/live chapter rows do not carry parent PDF bounds even
        # though every subsection/day does.  In that case list_pages_for_lesson
        # cannot perform the batch lookup.  Resolve each still-missing day by
        # its own internal PDF bounds, exactly like the selected-day path.
        # This affects only internal retrieval; teacher-facing values remain
        # printed/book-page labels.
        for subsection in unresolved:
            if not subsection.printed_start_page or not subsection.printed_end_page:
                self._hydrate_single_subsection_book_pages(subsection)


    def hydrate_subsection_book_pages(
        self,
        lesson: EmbeddingLessonMatch,
        subsection: EmbeddingSubsection,
    ) -> EmbeddingSubsection:
        """Public guard used immediately before day lesson generation.

        This deliberately re-resolves the selected day's printed/book range
        even if the list screen previously hydrated it. It protects against
        stale/raw subsection objects and older DB rows.
        """
        self._hydrate_subsection_book_pages(lesson, [subsection])
        if not subsection.printed_start_page or not subsection.printed_end_page:
            self._hydrate_single_subsection_book_pages(subsection)
        return subsection

    def _hydrate_single_subsection_book_pages(
        self,
        subsection: EmbeddingSubsection,
    ) -> None:
        """Recover a single day's book-page bounds directly from page metadata."""
        if subsection.printed_start_page and subsection.printed_end_page:
            return

        labels = [
            str(value).strip()
            for value in subsection.printed_page_numbers
            if str(value).strip()
        ]
        if labels:
            subsection.printed_start_page = subsection.printed_start_page or labels[0]
            subsection.printed_end_page = subsection.printed_end_page or labels[-1]
            if subsection.printed_start_page and subsection.printed_end_page:
                return

        if (
            not subsection.document_id
            or subsection.pdf_start_page is None
            or subsection.pdf_end_page is None
        ):
            return

        document_expr = (
            "CAST(:document_id AS uuid)"
            if not self.settings.database_is_sqlite
            else ":document_id"
        )
        sql = text(
            f"""
            SELECT
                pe.pdf_page_number,
                pe.printed_page_number,
                pe.printed_page_label
            FROM {self._schema_prefix}embeddings_page_extractions pe
            WHERE pe.document_id = {document_expr}
              AND pe.pdf_page_number BETWEEN :pdf_start_page AND :pdf_end_page
            ORDER BY pe.pdf_page_number
            """
        )
        try:
            rows = self.db.execute(
                sql,
                {
                    "document_id": subsection.document_id,
                    "pdf_start_page": subsection.pdf_start_page,
                    "pdf_end_page": subsection.pdf_end_page,
                },
            ).mappings().all()
        except SQLAlchemyError as exc:
            log_event(
                logger,
                "embedding_subsection_book_pages_lookup_failed",
                error=str(exc),
                subsection_id=subsection.id,
                document_id=subsection.document_id,
            )
            self.db.rollback()
            return

        page_labels: list[str] = []
        for row in rows:
            raw_number = row.get("printed_page_number")
            raw_label = row.get("printed_page_label")
            label = str(raw_number).strip() if raw_number is not None else ""
            if not label and raw_label is not None:
                label = str(raw_label).strip()
            if label:
                page_labels.append(label)

        if not page_labels:
            return

        subsection.printed_start_page = subsection.printed_start_page or page_labels[0]
        subsection.printed_end_page = subsection.printed_end_page or page_labels[-1]
        if not subsection.printed_page_numbers:
            subsection.printed_page_numbers = page_labels

    def resolve_page_choice(
        self,
        pages: list[EmbeddingPageExtraction],
        value: str | None,
    ) -> EmbeddingPageExtraction | None:
        """Resolve an exact printed/book-page label only.

        Physical PDF page numbers are intentionally not accepted from teacher
        input. They remain internal coordinates used to retrieve and validate a
        contiguous source slice.
        """
        raw = (value or "").strip()
        if not raw:
            return None
        normalized = raw.casefold().strip()
        normalized = re.sub(r"^(?:book\s*)?page\s*[:#-]?\s*", "", normalized)
        if normalized.startswith("pdf"):
            return None

        for page in pages:
            labels = {
                (page.printed_page_number or "").strip().casefold(),
                (page.printed_page_label or "").strip().casefold(),
            }
            labels.discard("")
            if normalized in labels:
                return page
        return None

    def _candidate_lessons(
        self,
        *,
        school_name: str | None = None,
        grade: str | None = None,
        subject: str | None = None,
        chapter_id: str | None = None,
    ) -> list[EmbeddingLessonMatch]:
        id_select = "CAST(c.id AS text)" if not self.settings.database_is_sqlite else "CAST(c.id AS TEXT)"
        doc_select = "CAST(d.id AS text)" if not self.settings.database_is_sqlite else "CAST(d.id AS TEXT)"
        where: list[str] = []
        params: dict[str, Any] = {}

        if chapter_id:
            where.append(f"c.id = {'CAST(:chapter_id AS uuid)' if not self.settings.database_is_sqlite else ':chapter_id'}")
            params["chapter_id"] = chapter_id
        else:
            if school_name:
                where.append("lower(d.school_name) = lower(:school_name)")
                params["school_name"] = school_name.strip()
        where_sql = " AND ".join(where) if where else "1=1"
        sql_text = f"""
            SELECT
                {doc_select} AS document_id,
                {id_select} AS chapter_id,
                d.document_key,
                d.school_name,
                d.grade,
                d.class_name,
                d.subject,
                d.book_title,
                c.chapter_number,
                c.chapter_title,
                c.unit_number,
                c.unit_title,
                c.section_number,
                c.section_title,
                c.lesson_title,
                c.structure_type,
                c.pdf_start_page,
                c.pdf_end_page,
                c.printed_start_page,
                c.printed_end_page,
                COALESCE(st.subsection_count, 0) AS subsection_count,
                COALESCE(st.lesson_text, '') AS text
            FROM {self._schema_prefix}embeddings_book_chapters c
            JOIN {self._schema_prefix}embeddings_documents d ON d.id = c.document_id
            LEFT JOIN (
                SELECT
                    document_id,
                    COALESCE(NULLIF(section_number, ''), NULLIF(chapter_number, ''), NULLIF(section_title, ''), NULLIF(chapter_title, '')) AS lesson_key,
                    count(*) AS subsection_count,
                    string_agg(COALESCE(NULLIF(subsection_text_plain, ''), subsection_text, ''), E'\n\n') AS lesson_text
                FROM {self._schema_prefix}embeddings_book_subsections
                GROUP BY document_id, COALESCE(NULLIF(section_number, ''), NULLIF(chapter_number, ''), NULLIF(section_title, ''), NULLIF(chapter_title, ''))
            ) st ON st.document_id = c.document_id
                AND st.lesson_key = COALESCE(NULLIF(c.section_number, ''), NULLIF(c.chapter_number, ''), NULLIF(c.section_title, ''), NULLIF(c.chapter_title, ''))
            WHERE {where_sql}
            ORDER BY d.school_name, d.grade, d.subject, c.pdf_start_page, c.chapter_number, c.section_number
        """
        if self.settings.database_is_sqlite:
            # The production embeddings tables are PostgreSQL, but this keeps local sqlite tests from failing
            # if someone creates lightweight compatible tables.
            sql_text = sql_text.replace("string_agg(", "group_concat(").replace(", E'\n\n')", ", '\n\n')")
        sql = text(sql_text)
        try:
            rows = self.db.execute(sql, params).mappings().all()
        except SQLAlchemyError as exc:
            log_event(logger, "embedding_lesson_candidates_failed", error=str(exc))
            self.db.rollback()
            return []

        lessons = [self._lesson_from_row(row) for row in rows]
        if not chapter_id:
            if grade:
                grade_variants = set(self._grade_variants(grade))
                lessons = [lesson for lesson in lessons if self._lesson_grade_key(lesson.grade) in grade_variants or self._lesson_grade_key(lesson.class_name) in grade_variants]
            if subject:
                subject_variants = set(self._subject_variants(subject))
                lessons = [lesson for lesson in lessons if (lesson.subject or "").strip().casefold() in subject_variants]
        return lessons

    def _lesson_from_row(self, row) -> EmbeddingLessonMatch:
        return EmbeddingLessonMatch(
            document_id=str(row.get("document_id") or ""),
            chapter_id=str(row.get("chapter_id") or ""),
            document_key=row.get("document_key"),
            school_name=row.get("school_name"),
            grade=row.get("grade"),
            class_name=row.get("class_name"),
            subject=row.get("subject"),
            book_title=row.get("book_title"),
            chapter_number=row.get("chapter_number"),
            chapter_title=row.get("chapter_title"),
            unit_number=row.get("unit_number"),
            unit_title=row.get("unit_title"),
            section_number=row.get("section_number"),
            section_title=row.get("section_title"),
            lesson_title=row.get("lesson_title"),
            structure_type=row.get("structure_type"),
            pdf_start_page=row.get("pdf_start_page"),
            pdf_end_page=row.get("pdf_end_page"),
            printed_start_page=row.get("printed_start_page"),
            printed_end_page=row.get("printed_end_page"),
            text=row.get("text") or "",
            subsection_count=int(row.get("subsection_count") or 0),
        )

    def _subsection_from_row(self, row) -> EmbeddingSubsection:
        printed_page_numbers = self._as_list(row.get("printed_page_numbers"))
        printed_labels = [str(value).strip() for value in printed_page_numbers if str(value).strip()]
        printed_start_page = row.get("printed_start_page")
        printed_end_page = row.get("printed_end_page")
        if printed_labels:
            printed_start_page = printed_start_page or printed_labels[0]
            printed_end_page = printed_end_page or printed_labels[-1]

        return EmbeddingSubsection(
            id=str(row.get("id") or ""),
            document_id=str(row.get("document_id") or ""),
            subsection_number=row.get("subsection_number"),
            subsection_title=row.get("subsection_title"),
            anchor_marker=row.get("anchor_marker"),
            pdf_start_page=row.get("pdf_start_page"),
            pdf_end_page=row.get("pdf_end_page"),
            printed_start_page=(str(printed_start_page).strip() if printed_start_page is not None else None),
            printed_end_page=(str(printed_end_page).strip() if printed_end_page is not None else None),
            page_numbers=self._as_list(row.get("page_numbers")),
            printed_page_numbers=printed_page_numbers,
            includes=self._as_list(row.get("includes")),
            text=row.get("text") or "",
            text_length_chars=row.get("text_length_chars"),
            include_in_embeddings=row.get("include_in_embeddings"),
            embedding_readiness=row.get("embedding_readiness"),
            quality_flags=self._as_list(row.get("quality_flags")),
        )

    def _teacher_schedule_from_row(self, row) -> EmbeddingTeacherSchedule:
        return EmbeddingTeacherSchedule(
            id=str(row.get("id") or ""),
            document_id=str(row.get("document_id") or ""),
            schedule_key=row.get("schedule_key"),
            chapter_number=(str(row.get("chapter_number")).strip() if row.get("chapter_number") is not None else None),
            chapter_title=row.get("chapter_title"),
            section_number=(str(row.get("section_number")).strip() if row.get("section_number") is not None else None),
            section_title=row.get("section_title"),
            week_start_date=self._date_as_string(row.get("week_start_date")),
            schedule_source=row.get("schedule_source"),
            schedule_type=row.get("schedule_type"),
            exercise=(str(row.get("exercise")).strip() if row.get("exercise") is not None else None),
            schedule_note=row.get("schedule_note"),
            day_count=int(row.get("day_count") or 0),
        )

    def _teacher_schedule_day_from_row(self, row) -> EmbeddingTeacherScheduleDay:
        return EmbeddingTeacherScheduleDay(
            id=str(row.get("id") or ""),
            teacher_schedule_id=str(row.get("teacher_schedule_id") or ""),
            document_id=str(row.get("document_id") or ""),
            day=self._coerce_int(row.get("day")),
            weekday=(str(row.get("weekday")).strip() if row.get("weekday") is not None else None),
            day_type=(str(row.get("day_type")).strip() if row.get("day_type") is not None else None),
            activity=(str(row.get("activity")).strip() if row.get("activity") is not None else None),
            topic=(str(row.get("topic")).strip() if row.get("topic") is not None else None),
            teaching_book_page_ranges=self._as_json_list(row.get("teaching_book_page_ranges")),
            exercise_book_pages=self._as_int_list(row.get("exercise_book_pages")),
            exercise=(str(row.get("exercise")).strip() if row.get("exercise") is not None else None),
            questions=[str(value).strip() for value in self._as_list(row.get("questions")) if str(value).strip()],
            range_source=(str(row.get("range_source")).strip() if row.get("range_source") is not None else None),
            source_input_warning=(str(row.get("source_input_warning")).strip() if row.get("source_input_warning") is not None else None),
            selected_book_pages=self._as_int_list(row.get("selected_book_pages")),
            selected_pdf_pages=self._as_int_list(row.get("selected_pdf_pages")),
            selected_page_count=self._coerce_int(row.get("selected_page_count")),
            selection_is_contiguous=row.get("selection_is_contiguous"),
            display_book_pages=(str(row.get("display_book_pages")).strip() if row.get("display_book_pages") is not None else None),
            display_pdf_pages=(str(row.get("display_pdf_pages")).strip() if row.get("display_pdf_pages") is not None else None),
            selection_policy=(str(row.get("selection_policy")).strip() if row.get("selection_policy") is not None else None),
            selected_pages_available=row.get("selected_pages_available"),
        )

    @staticmethod
    def _teacher_schedule_matches_lesson(
        schedule: EmbeddingTeacherSchedule,
        lesson: EmbeddingLessonMatch,
    ) -> bool:
        if schedule.document_id != lesson.document_id:
            return False
        if lesson.chapter_number and schedule.chapter_number:
            return str(schedule.chapter_number).strip().casefold() == str(lesson.chapter_number).strip().casefold()
        if lesson.section_number and schedule.section_number:
            return str(schedule.section_number).strip().casefold() == str(lesson.section_number).strip().casefold()
        if lesson.chapter_title and schedule.chapter_title:
            return schedule.chapter_title.strip().casefold() == lesson.chapter_title.strip().casefold()
        if lesson.section_title and schedule.section_title:
            return schedule.section_title.strip().casefold() == lesson.section_title.strip().casefold()
        return False

    @staticmethod
    def _date_as_string(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, (date, datetime)):
            return value.strftime("%Y-%m-%d")
        text_value = str(value).strip()
        return text_value[:10] if text_value else None

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _as_int_list(self, value: Any) -> list[int]:
        result: list[int] = []
        for item in self._as_list(value):
            parsed = self._coerce_int(item)
            if parsed is not None:
                result.append(parsed)
        return result

    @staticmethod
    def _as_json_list(value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, tuple):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        return []

    def _as_list(self, value) -> list:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("[") and raw.endswith("]"):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    pass
            stripped = value.strip("{}")
            if not stripped:
                return []
            return [item.strip().strip('"') for item in stripped.split(",") if item.strip()]
        return list(value) if hasattr(value, "__iter__") else []

    def _normalize_title(self, value: str | None) -> str:
        cleaned = re.sub(r"[^0-9a-zA-Z\u0900-\u097F]+", " ", value or "").casefold()
        tokens = [token for token in cleaned.split() if token not in _TOPIC_STOPWORDS]
        return " ".join(tokens)

    def _tokens(self, value: str | None) -> list[str]:
        return [token for token in self._normalize_title(value).split() if token]

    def _title_score(self, topic_norm: str, topic_tokens: set[str], candidate_title: str | None) -> int:
        title_norm = self._normalize_title(candidate_title)
        if not topic_norm or not title_norm:
            return 0
        if topic_norm == title_norm:
            return 1000
        if topic_norm in title_norm or title_norm in topic_norm:
            return 800
        title_tokens = set(title_norm.split())
        if not title_tokens or not topic_tokens:
            return 0
        overlap = len(topic_tokens & title_tokens)
        if len(topic_tokens) == 1:
            return 500 if overlap == 1 else 0
        ratio = overlap / max(1, len(topic_tokens))
        if ratio >= 0.75:
            return 400 + overlap * 20
        return 0

    def _grade_variants(self, grade: str) -> list[str]:
        raw = (grade or "").strip().casefold()
        number = "".join(ch for ch in raw if ch.isdigit())
        variants = {raw.replace(" ", "")}
        if number:
            variants.update({number, f"class-{number}", f"class{number}", f"grade-{number}", f"grade{number}"})
        return sorted(variants)

    def _lesson_grade_key(self, value: str | None) -> str:
        return (value or "").strip().casefold().replace(" ", "")

    def _subject_variants(self, subject: str) -> list[str]:
        normalized_subject = normalize_subject(subject)
        normalized = normalized_subject.casefold()
        variants = {normalized, (subject or "").strip().casefold()}

        if normalized in {"math", "maths", "mathematics"}:
            variants.update({"math", "maths", "mathematics"})

        if normalized == "environmental studies":
            variants.update({
                "environmental studies",
                "environment studies",
                "environmental science",
                "evs",
                "e v s",
                "the world around us",
                "world around us",
                "our wondrous world",
                "wondrous world",
            })

        return sorted(item for item in variants if item)

    def _is_numeric_lesson_number(self, value: str | None) -> bool:
        return bool(re.fullmatch(r"\d+(?:\.\d+)?", (value or "").strip()))

    def _numeric_lesson_number(self, value: str | None) -> float:
        try:
            return float((value or "").strip())
        except ValueError:
            return float("inf")
