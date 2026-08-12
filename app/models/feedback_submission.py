from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FeedbackSubmission(Base):
    __tablename__ = "feedback_submission"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teacher_profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    whatsapp_number: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    survey_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    survey_version: Mapped[int] = mapped_column(Integer, nullable=False)

    # Snapshot the teacher profile so historical feedback stays understandable
    # even if the teacher changes school, grade, subject, or language later.
    teacher_name: Mapped[str] = mapped_column(String(255), nullable=False)
    school_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    grade: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(50), nullable=False)

    answers_json: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    teacher = relationship("TeacherProfile", back_populates="feedback_submissions")
