from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger, log_event
from app.utils.subject_normalization import normalize_subject

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
    printed_start_page: int | None
    printed_end_page: int | None
    text: str
    subsection_count: int = 0
    match_score: int = 0

    @property
    def title(self) -> str:
        return (
            self.section_title
            or self.lesson_title
            or self.chapter_title
            or self.book_title
            or "Selected lesson"
        ).strip()

    @property
    def display_pages(self) -> str:
        if self.printed_start_page and self.printed_end_page:
            return f"{self.printed_start_page}-{self.printed_end_page}"
        if self.pdf_start_page and self.pdf_end_page:
            return f"PDF {self.pdf_start_page}-{self.pdf_end_page}"
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
    printed_start_page: int | None
    printed_end_page: int | None
    page_numbers: list[int]
    printed_page_numbers: list[int]
    includes: list[str]
    text: str
    text_length_chars: int | None
    include_in_embeddings: bool | None
    embedding_readiness: str | None
    quality_flags: list[str]

    @property
    def title(self) -> str:
        return (self.subsection_title or self.anchor_marker or self.subsection_number or "Day").strip()

    @property
    def display_pages(self) -> str:
        if self.printed_start_page and self.printed_end_page:
            return f"{self.printed_start_page}-{self.printed_end_page}"
        if self.pdf_start_page and self.pdf_end_page:
            return f"PDF {self.pdf_start_page}-{self.pdf_end_page}"
        return "Not available"


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

        return [self._subsection_from_row(row) for row in rows]

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
        return self._subsection_from_row(row) if row else None

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
        return EmbeddingSubsection(
            id=str(row.get("id") or ""),
            document_id=str(row.get("document_id") or ""),
            subsection_number=row.get("subsection_number"),
            subsection_title=row.get("subsection_title"),
            anchor_marker=row.get("anchor_marker"),
            pdf_start_page=row.get("pdf_start_page"),
            pdf_end_page=row.get("pdf_end_page"),
            printed_start_page=row.get("printed_start_page"),
            printed_end_page=row.get("printed_end_page"),
            page_numbers=self._as_list(row.get("page_numbers")),
            printed_page_numbers=self._as_list(row.get("printed_page_numbers")),
            includes=self._as_list(row.get("includes")),
            text=row.get("text") or "",
            text_length_chars=row.get("text_length_chars"),
            include_in_embeddings=row.get("include_in_embeddings"),
            embedding_readiness=row.get("embedding_readiness"),
            quality_flags=self._as_list(row.get("quality_flags")),
        )

    def _as_list(self, value) -> list:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, str):
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
        normalized = normalize_subject(subject).casefold()
        variants = {normalized, (subject or "").strip().casefold()}
        if normalized in {"math", "maths", "mathematics"}:
            variants.update({"math", "maths", "mathematics"})
        return sorted(item for item in variants if item)
