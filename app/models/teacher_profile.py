from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TeacherProfile(Base):
    __tablename__ = "teacher_profile"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    whatsapp_number: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    teacher_name: Mapped[str] = mapped_column(String(255), nullable=False)
    default_grade: Mapped[str] = mapped_column(String(100), nullable=False)
    default_subject: Mapped[str] = mapped_column(String(100), nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(50), nullable=False, default="English")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    lessons = relationship("LessonPlan", back_populates="teacher", cascade="all, delete-orphan")
    sent_lesson_shares = relationship(
        "LessonShare",
        foreign_keys="LessonShare.shared_by_teacher_id",
        back_populates="shared_by_teacher",
    )
    received_lesson_shares = relationship(
        "LessonShare",
        foreign_keys="LessonShare.shared_with_teacher_id",
        back_populates="shared_with_teacher",
    )
