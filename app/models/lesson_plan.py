from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class LessonPlan(Base):
    __tablename__ = "lesson_plan"
    __table_args__ = (
        UniqueConstraint("teacher_id", "lesson_name", name="uq_teacher_lesson_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teacher_profile.id"), nullable=False, index=True)
    lesson_name: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    grade: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    lesson_text: Mapped[str] = mapped_column(Text, nullable=False)
    lesson_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Source references for lessons generated from pdf_to_embeddings.
    # Kept as nullable so older/generic lesson plans continue to work.
    document_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    document_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    book_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    school_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chapter_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    subsection_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    chapter_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subsection_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    subsection_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    day_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    day_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    book_pages: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pdf_start_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pdf_end_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    printed_start_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    printed_end_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resource_profile: Mapped[str | None] = mapped_column(String(100), nullable=True)
    format_profile: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    teacher = relationship("TeacherProfile", back_populates="lessons")
    shares = relationship("LessonShare", back_populates="lesson", cascade="all, delete-orphan")
