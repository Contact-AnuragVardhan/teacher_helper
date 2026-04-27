from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class LessonShare(Base):
    __tablename__ = "lesson_share"
    __table_args__ = (
        UniqueConstraint("lesson_id", "shared_with_teacher_id", name="uq_lesson_shared_with_teacher"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    lesson_id: Mapped[int] = mapped_column(
        ForeignKey("lesson_plan.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shared_by_teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teacher_profile.id"),
        nullable=False,
        index=True,
    )
    shared_with_teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teacher_profile.id"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    lesson = relationship("LessonPlan", back_populates="shares")
    shared_by_teacher = relationship(
        "TeacherProfile",
        foreign_keys=[shared_by_teacher_id],
        back_populates="sent_lesson_shares",
    )
    shared_with_teacher = relationship(
        "TeacherProfile",
        foreign_keys=[shared_with_teacher_id],
        back_populates="received_lesson_shares",
    )
