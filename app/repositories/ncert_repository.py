from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_event
from app.models.ncert_content import NcertContent

logger = get_logger(__name__)


class NcertContentRepository:
    def __init__(self, db: Session):
        self.db = db

    def truncate(self) -> None:
        self.db.query(NcertContent).delete()
        self.db.commit()
        log_event(logger, "ncert_repository_truncated")

    def bulk_create(self, rows: list[NcertContent]) -> int:
        self.db.add_all(rows)
        self.db.commit()
        log_event(logger, "ncert_repository_bulk_create", row_count=len(rows))
        return len(rows)

    def find_by_grade_and_subject(self, grade: str, subject: str) -> list[NcertContent]:
        rows = (
            self.db.query(NcertContent)
            .filter(
                func.lower(NcertContent.grade) == grade.strip().lower(),
                func.lower(NcertContent.subject) == subject.strip().lower(),
            )
            .order_by(NcertContent.id.asc())
            .all()
        )
        log_event(
            logger,
            "ncert_repository_lookup",
            grade=grade,
            subject=subject,
            row_count=len(rows),
        )
        return rows
