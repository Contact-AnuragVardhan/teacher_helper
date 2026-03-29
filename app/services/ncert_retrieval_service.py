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
    source_title: str
    chapter: str | None
    topic: str | None
    content_chunk: str
    score: int
    exact_matches: list[str]
    partial_matches: list[str]

    def as_prompt_snippet(self) -> str:
        labels = [self.source_title]
        if self.chapter:
            labels.append(f"Chapter: {self.chapter}")
        if self.topic:
            labels.append(f"Topic: {self.topic}")
        header = " | ".join(labels)
        return f"[{header}] {self.content_chunk}"


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
                    source_title=row.source_title,
                    chapter=row.chapter,
                    topic=row.topic,
                    content_chunk=row.content_chunk,
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
            filter(None, [row.topic, row.chapter, row.source_title, row.keywords, row.content_chunk])
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
