from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TeacherChatActivity(Base):
    """A timestamp-only audit row used for simple Teacher Helper usage reporting."""

    __tablename__ = "teacher_chat_activity"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teacher_profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    whatsapp_number: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    teacher = relationship("TeacherProfile", back_populates="chat_activities")
