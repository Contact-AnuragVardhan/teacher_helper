import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger, log_event
from app.models.ncert_content import NcertContent
from app.repositories.ncert_repository import NcertContentRepository

logger = get_logger(__name__)

_TOPIC_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is", "it",
    "of", "on", "or", "the", "to", "with", "without", "about", "after", "before", "over", "under",
    "this", "that", "these", "those", "lesson", "chapter", "topic", "class", "grade", "subject",
}


@dataclass(slots=True)
class RetrievedChunk:
    id: int
    grade: str
    subject: str
    source_title: str
    chapter: str | None
    topic: str | None
    book: str | None
    book_url: str | None
    unit_name: str | None
    topic_name: str | None
    topic_summary: str | None
    lesson_goal: str | None
    source_reference: str | None
    content_chunk: str
    keywords: str | None
    score: int
    exact_matches: list[str]
    partial_matches: list[str]

    def as_prompt_snippet(self) -> str:
        topic_label = self.topic_name or self.topic or "Unknown topic"
        unit_label = self.unit_name or self.chapter or "Unknown unit"
        summary = (self.topic_summary or self.content_chunk or "").strip()
        goal = (self.lesson_goal or "").strip()
        source = (self.source_reference or self.source_title or "").strip()

        parts = [
            f"Grade: {self.grade}",
            f"Subject: {self.subject}",
        ]
        if self.book:
            parts.append(f"Book: {self.book}")
        parts.extend(
            [
                f"Unit: {unit_label}",
                f"Topic: {topic_label}",
            ]
        )
        if summary:
            parts.append(f"Topic Summary: {summary}")
        if goal:
            parts.append(f"Lesson Goal: {goal}")
        if source:
            parts.append(f"Source: {source}")
        return "\n".join(parts)

    def as_inspectable_row(self) -> dict:
        return {
            "id": self.id,
            "grade": self.grade,
            "subject": self.subject,
            "book": self.book,
            "book_url": self.book_url,
            "chapter": self.chapter,
            "unit_name": self.unit_name or self.chapter,
            "topic_name": self.topic_name or self.topic,
            "topic_summary": self.topic_summary or self.content_chunk,
            "lesson_goal": self.lesson_goal,
            "keywords": self.keywords,
            "source_reference": self.source_reference or self.source_title,
            "score": self.score,
            "exact_matches": self.exact_matches,
            "partial_matches": self.partial_matches,
        }


class NcertRetrievalService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = NcertContentRepository(db)
        self.settings = get_settings()

    def retrieve(self, *, grade: str, subject: str, topic: str, top_k: int | None = None) -> list[RetrievedChunk]:
        rows = self.repo.find_by_grade_and_subject(grade=grade, subject=subject)
        topic_tokens = self._topic_tokens(topic)

        if not topic_tokens:
            log_event(
                logger,
                "ncert_retrieval_no_meaningful_tokens",
                grade=grade,
                subject=subject,
                topic=topic,
                candidates=len(rows),
            )
            return []

        scored: list[RetrievedChunk] = []
        for row in rows:
            score, exact_matches, partial_matches = self._score_row(row, topic, topic_tokens)
            if not self._is_confident_match(topic_tokens, exact_matches, partial_matches):
                continue

            scored.append(
                RetrievedChunk(
                    id=row.id,
                    grade=row.grade,
                    subject=row.subject,
                    source_title=row.source_title,
                    chapter=row.chapter,
                    topic=row.topic,
                    book=row.book,
                    book_url=row.book_url,
                    unit_name=row.unit_name,
                    topic_name=row.topic_name,
                    topic_summary=row.topic_summary,
                    lesson_goal=row.lesson_goal,
                    source_reference=row.source_reference,
                    content_chunk=row.content_chunk,
                    keywords=row.keywords,
                    score=score,
                    exact_matches=exact_matches,
                    partial_matches=partial_matches,
                )
            )

        limit = min(top_k or self.settings.ncert_top_k, 3)
        ranked = sorted(
            scored,
            key=lambda item: (
                item.score,
                len(set(item.exact_matches)),
                len(set(item.partial_matches)),
            ),
            reverse=True,
        )[:limit]

        log_event(
            logger,
            "ncert_retrieval",
            grade=grade,
            subject=subject,
            topic=topic,
            topic_tokens=topic_tokens,
            candidates=len(rows),
            returned=[
                {
                    "id": item.id,
                    "score": item.score,
                    "source_title": item.source_title,
                    "chapter": item.chapter,
                    "topic_name": item.topic_name,
                    "exact_matches": item.exact_matches,
                    "partial_matches": item.partial_matches,
                }
                for item in ranked
            ],
        )
        return ranked

    def _normalize_text(self, value: str | None) -> str:
        return re.sub(r"\s+", " ", (value or "").strip()).casefold()

    def _score_row(self, row: NcertContent, topic: str, topic_tokens: list[str]) -> tuple[int, list[str], list[str]]:
        requested = self._normalize_text(topic)

        topic_name = self._normalize_text(row.topic_name or row.topic)
        source_title = self._normalize_text(row.source_title)
        unit_name = self._normalize_text(row.unit_name or row.chapter)
        keywords = self._normalize_text(row.keywords)
        summary = self._normalize_text(row.topic_summary)
        content = self._normalize_text(row.content_chunk)

        exact_matches: list[str] = []
        partial_matches: list[str] = []
        score = 0

        if requested and requested == topic_name:
            score += 5000
        elif requested and requested in topic_name:
            score += 2500

        if requested and requested in source_title:
            score += 2000

        title_blob = " ".join(filter(None, [topic_name, source_title, unit_name, keywords]))
        weak_blob = " ".join(filter(None, [summary, content]))

        title_tokens = set(re.findall(r"[a-z0-9-]+", title_blob))
        weak_tokens = set(re.findall(r"[a-z0-9-]+", weak_blob))

        for token in topic_tokens:
            if token in title_tokens:
                exact_matches.append(token)
                score += 300
            elif token in title_blob:
                partial_matches.append(token)
                score += 100
            elif token in weak_tokens:
                exact_matches.append(token)
                score += 20
            elif token in weak_blob:
                partial_matches.append(token)
                score += 5

        return score, exact_matches, partial_matches

    def _is_confident_match(
        self,
        topic_tokens: list[str],
        exact_matches: list[str],
        partial_matches: list[str],
    ) -> bool:
        token_count = len(topic_tokens)
        exact_count = len(set(exact_matches))
        matched_count = len(set(exact_matches + partial_matches))

        if token_count == 0:
            return False

        if token_count == 1:
            return exact_count >= 1 or matched_count >= 1

        if token_count == 2:
            return exact_count >= 2 or (exact_count >= 1 and matched_count == 2)

        return exact_count >= 2 or matched_count >= 3

    def _topic_tokens(self, topic: str) -> list[str]:
        raw_tokens = re.findall(r"[a-z0-9-]+", topic.casefold())
        return [
            token
            for token in raw_tokens
            if len(token) > 2 and token not in _TOPIC_STOPWORDS
        ]