from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ncert_content import NcertContent


class NcertContentRepository:
    def __init__(self, db: Session):
        self.db = db

    def truncate(self) -> None:
        self.db.query(NcertContent).delete()
        self.db.commit()

    def bulk_create(self, rows: list[NcertContent]) -> int:
        self.db.add_all(rows)
        self.db.commit()
        return len(rows)

    def find_by_grade_and_subject(self, grade: str, subject: str) -> list[NcertContent]:
        return (
            self.db.query(NcertContent)
            .filter(
                func.lower(NcertContent.grade) == grade.strip().lower(),
                func.lower(NcertContent.subject) == subject.strip().lower(),
            )
            .order_by(NcertContent.id.asc())
            .all()
        )
