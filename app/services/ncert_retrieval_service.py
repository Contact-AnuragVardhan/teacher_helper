import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger, log_event
from app.models.ncert_content import NcertContent
from app.repositories.ncert_repository import NcertContentRepository

logger = get_logger(__name__)


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
        summary = (self.topic_summary or self.content_chunk).strip()
        goal = (self.lesson_goal or "").strip()
        keywords = (self.keywords or "").strip()
        source = (self.source_reference or self.source_title).strip()

        parts = [
            f"Grade: {self.grade}",
            f"Subject: {self.subject}",
        ]
        if self.book:
            parts.append(f"Book: {self.book}")
        if self.book_url:
            parts.append(f"Book URL: {self.book_url}")
        parts.extend(
            [
                f"Unit: {unit_label}",
                f"Topic: {topic_label}",
                f"Topic Summary: {summary}",
            ]
        )
        if goal:
            parts.append(f"Lesson Goal: {goal}")
        if keywords:
            parts.append(f"Keywords: {keywords}")
        parts.append(f"Source: {source}")
        return "\n".join(parts)

    def as_inspectable_row(self) -> dict:
        return {
            "id": self.id,
            "grade": self.grade,
            "subject": self.subject,
            "book": self.book,
            "book_url": self.book_url,
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

        scored: list[RetrievedChunk] = []
        for row in rows:
            score, exact_matches, partial_matches = self._score_row(row, topic_tokens)
            if topic_tokens and score <= 0:
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
                len(item.exact_matches),
                len(item.partial_matches),
                -item.id,
            ),
            reverse=True,
        )[:limit]

        log_event(
            logger,
            "ncert_retrieval",
            grade=grade,
            subject=subject,
            topic=topic,
            candidates=len(rows),
            returned=[
                {
                    "id": item.id,
                    "score": item.score,
                    "source_title": item.source_title,
                    "topic_name": item.topic_name,
                    "exact_matches": item.exact_matches,
                    "partial_matches": item.partial_matches,
                }
                for item in ranked
            ],
        )
        return ranked

    def _score_row(self, row: NcertContent, topic_tokens: list[str]) -> tuple[int, list[str], list[str]]:
        if not topic_tokens:
            return 1, [], []

        searchable = " ".join(
            filter(
                None,
                [
                    row.topic,
                    row.topic_name,
                    row.chapter,
                    row.book,
                    row.book_url,
                    row.unit_name,
                    row.source_title,
                    row.source_reference,
                    row.keywords,
                    row.topic_summary,
                    row.lesson_goal,
                    row.content_chunk,
                ],
            )
        ).casefold()
        exact_token_set = set(re.findall(r"[a-z0-9-]+", searchable))

        exact_matches: list[str] = []
        partial_matches: list[str] = []
        score = 0
        for token in topic_tokens:
            if token in exact_token_set:
                exact_matches.append(token)
                score += 100
            elif token in searchable:
                partial_matches.append(token)
                score += 30

        score += 5
        return score, exact_matches, partial_matches

    def _topic_tokens(self, topic: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9-]+", topic.casefold())
        return [token for token in tokens if len(token) > 1]