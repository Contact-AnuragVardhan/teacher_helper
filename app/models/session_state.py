from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
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
    temp_selected_lesson_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temp_profile_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temp_profile_grade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temp_profile_subject: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temp_profile_school: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temp_content_document_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    temp_content_chapter_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    temp_content_subsection_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    temp_teacher_schedule_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    temp_teacher_schedule_day_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    temp_lesson_day_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temp_lesson_day_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temp_lesson_book_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temp_lesson_chapter_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temp_lesson_section_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temp_lesson_subsection_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    temp_lesson_subsection_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temp_lesson_book_pages: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temp_lesson_pdf_start_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temp_lesson_pdf_end_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temp_lesson_printed_start_page: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temp_lesson_printed_end_page: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temp_lesson_document_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temp_lesson_school_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temp_lesson_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    temp_customize_from_page: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temp_customize_to_page: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temp_lesson_is_customized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    temp_feedback_survey_key: Mapped[str | None] = mapped_column(String(140), nullable=True)
    temp_feedback_question_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temp_feedback_answers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    temp_admin_report_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    temp_admin_teacher_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
