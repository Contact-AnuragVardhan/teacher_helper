from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NcertContent(Base):
    __tablename__ = "ncert_content"
    __table_args__ = (
        Index("ix_ncert_content_grade_subject", "grade", "subject"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    grade: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    chapter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_chunk: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
