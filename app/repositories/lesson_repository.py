from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.lesson_plan import LessonPlan


class LessonRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_teacher_and_name(self, teacher_id: int, lesson_name: str) -> LessonPlan | None:
        normalized_name = lesson_name.strip().lower()
        return (
            self.db.query(LessonPlan)
            .filter(
                LessonPlan.teacher_id == teacher_id,
                func.lower(LessonPlan.lesson_name) == normalized_name,
            )
            .first()
        )

    def create(
        self,
        *,
        teacher_id: int,
        lesson_name: str,
        topic: str,
        grade: str,
        subject: str,
        duration_minutes: int,
        lesson_text: str,
    ) -> LessonPlan:
        lesson = LessonPlan(
            teacher_id=teacher_id,
            lesson_name=lesson_name.strip(),
            topic=topic.strip(),
            grade=grade.strip(),
            subject=subject.strip(),
            duration_minutes=duration_minutes,
            lesson_text=lesson_text,
        )
        self.db.add(lesson)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise
        self.db.refresh(lesson)
        return lesson

    def overwrite(
        self,
        lesson: LessonPlan,
        *,
        topic: str,
        grade: str,
        subject: str,
        duration_minutes: int,
        lesson_text: str,
    ) -> LessonPlan:
        lesson.topic = topic.strip()
        lesson.grade = grade.strip()
        lesson.subject = subject.strip()
        lesson.duration_minutes = duration_minutes
        lesson.lesson_text = lesson_text
        self.db.add(lesson)
        self.db.commit()
        self.db.refresh(lesson)
        return lesson

    def create_or_update_by_policy(
        self,
        *,
        teacher_id: int,
        lesson_name: str,
        topic: str,
        grade: str,
        subject: str,
        duration_minutes: int,
        lesson_text: str,
    ) -> LessonPlan | None:
        settings = get_settings()
        existing = self.get_by_teacher_and_name(teacher_id, lesson_name)
        if existing:
            if settings.duplicate_lesson_policy == "reject":
                return None
            return self.overwrite(
                existing,
                topic=topic,
                grade=grade,
                subject=subject,
                duration_minutes=duration_minutes,
                lesson_text=lesson_text,
            )

        return self.create(
            teacher_id=teacher_id,
            lesson_name=lesson_name,
            topic=topic,
            grade=grade,
            subject=subject,
            duration_minutes=duration_minutes,
            lesson_text=lesson_text,
        )
