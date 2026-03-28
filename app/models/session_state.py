from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SessionState(Base):
    __tablename__ = "session_state"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    whatsapp_number: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    current_state: Mapped[str] = mapped_column(String(50), nullable=False, default="MAIN_MENU")
    temp_topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temp_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temp_generated_lesson: Mapped[str | None] = mapped_column(Text, nullable=True)
    temp_lesson_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temp_profile_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temp_profile_grade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temp_profile_subject: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
